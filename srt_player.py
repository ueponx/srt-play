import tkinter as tk
from tkinter import filedialog, scrolledtext
import pygame
import threading
import time
import re
import os
import sys
import argparse

# このコードでは音声ファイルの長さ取得に mutagen ライブラリを使用します
# pip install mutagen でインストールしてください
try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

class SRTPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("SRT Player")
        self.root.geometry("800x600")
        
        # Initialize pygame mixer for audio playback
        pygame.init()
        pygame.mixer.init()
        
        # Variables
        self.audio_file = ""
        self.srt_file = ""
        self.subtitles = []
        self.playing = False
        self.paused = False
        self.total_length = 100.0  # デフォルト値
        
        # 時間管理のための変数
        self.current_position = 0.0  # 現在の再生位置（秒）
        self.paused_position = 0.0   # 一時停止した位置（秒）
        self.initial_position = 0.0  # 再生開始位置
        
        # 字幕履歴の管理
        self.subtitle_history = []   # 表示した字幕の履歴
        self.last_subtitle_id = ""   # 最後に表示した字幕のID
        
        # スレッド制御
        self.stop_thread = False
        self.subtitle_thread = None
        
        # Set application theme and style
        self.root.configure(bg='#f0f0f0')
        
        # Create the GUI elements
        self.create_widgets()
    
    def create_widgets(self):
        # Frame for buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # 共通のボタンスタイル
        button_style = {'font': ('TkDefaultFont', 12), 'width': 12, 'height': 2}
        
        # ボタンを横方向に並べるのではなく、gridで配置
        self.audio_btn = tk.Button(button_frame, text="Select Audio", command=self.load_audio, **button_style)
        self.audio_btn.grid(row=0, column=0, padx=5, pady=5)
        
        self.srt_btn = tk.Button(button_frame, text="Select SRT", command=self.load_srt, **button_style)
        self.srt_btn.grid(row=0, column=1, padx=5, pady=5)
        
        self.play_btn = tk.Button(button_frame, text="Play", command=self.play, state=tk.DISABLED, **button_style)
        self.play_btn.grid(row=0, column=2, padx=5, pady=5)
        
        self.pause_btn = tk.Button(button_frame, text="Pause", command=self.pause, state=tk.DISABLED, **button_style)
        self.pause_btn.grid(row=0, column=3, padx=5, pady=5)
        
        self.stop_btn = tk.Button(button_frame, text="Stop", command=self.stop, state=tk.DISABLED, **button_style)
        self.stop_btn.grid(row=0, column=4, padx=5, pady=5)
        
        # ボタンの配置に合わせてグリッドを調整
        for i in range(5):
            button_frame.columnconfigure(i, weight=1)
            
        # シークバーの追加
        seek_frame = tk.Frame(self.root)
        seek_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.seek_var = tk.DoubleVar()
        self.seek_bar = tk.Scale(
            seek_frame, 
            variable=self.seek_var,
            from_=0, 
            to=100,  # 仮の値、音声読み込み時に更新
            orient=tk.HORIZONTAL, 
            length=700,
            showvalue=0,
            command=self.on_seek
        )
        self.seek_bar.pack(fill=tk.X, expand=True)
        
        # 時間表示ラベル（現在時間/総時間）
        self.duration_label = tk.Label(seek_frame, text="00:00/00:00", font=('TkDefaultFont', 10))
        self.duration_label.pack(side=tk.RIGHT, padx=5)
            
        # Info labels
        info_frame = tk.Frame(self.root)
        info_frame.pack(fill=tk.X, padx=10)
        
        tk.Label(info_frame, text="Audio File:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.audio_label = tk.Label(info_frame, text="No file selected")
        self.audio_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(info_frame, text="SRT File:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.srt_label = tk.Label(info_frame, text="No file selected")
        self.srt_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(info_frame, text="Current Time:", font=('TkDefaultFont', 12)).grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.time_label = tk.Label(info_frame, text="00:00:00,000", font=('TkDefaultFont', 16, 'bold'))
        self.time_label.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Subtitle display area
        subtitle_frame = tk.Frame(self.root)
        subtitle_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.subtitle_display = scrolledtext.ScrolledText(
            subtitle_frame, 
            wrap=tk.WORD, 
            font=("TkDefaultFont", 16),
            bg='#fafafa',
            padx=10,
            pady=10
        )
        self.subtitle_display.pack(fill=tk.BOTH, expand=True)
        
        # 自動スクロールを有効化するチェックボックス
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.autoscroll_check = tk.Checkbutton(
            subtitle_frame, 
            text="自動スクロール", 
            variable=self.autoscroll_var,
            font=('TkDefaultFont', 10)
        )
        self.autoscroll_check.pack(anchor=tk.W, padx=10, pady=2)
    
    def on_seek(self, value):
        """シークバーの値が変更されたときに呼ばれる"""
        if not self.playing and not self.paused:
            return
            
        # 値をfloatに変換
        value = float(value)
        
        # 音声の総時間に対する割合を計算
        if hasattr(self, 'total_length') and self.total_length > 0:
            position = (value / 100.0) * self.total_length
            
            # 内部変数を更新
            self.current_position = position
            
            # 再生中なら再生位置を更新、一時停止中なら再生せずに位置だけ更新
            if self.playing:
                pygame.mixer.music.stop()
                pygame.mixer.music.play(start=position)
                self.initial_position = position
            else:  # paused状態
                self.paused_position = position
                self.initial_position = position
                # 一時停止中は再生を開始しない
                
            # 時間表示を更新
            time_str = self.format_time(position)
            self.time_label.config(text=time_str)
            
            # 字幕履歴をクリア（新しい位置から履歴を構築し直す）
            self.subtitle_history = []
            self.last_subtitle_id = ""
            
            # テキストエリアをクリア
            self.subtitle_display.delete(1.0, tk.END)
    
    def load_audio(self):
        self.audio_file = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")]
        )
        if self.audio_file:
            self.audio_label.config(text=os.path.basename(self.audio_file))
            
            # 音声ファイルの長さを取得
            if MUTAGEN_AVAILABLE:
                try:
                    audio = mutagen.File(self.audio_file)
                    if audio and hasattr(audio.info, 'length'):
                        self.total_length = audio.info.length  # 総時間（秒）
                    else:
                        # mutagenで取得できない場合は仮の値を設定
                        self.total_length = 100.0
                except Exception:
                    self.total_length = 100.0
            else:
                # mutagenがインストールされていない場合は仮の値を設定
                self.total_length = 100.0
            
            # シークバーの最大値を設定（パーセント表示のため常に100）
            self.seek_bar.config(to=100)
            
            # 時間表示を更新
            duration_str = f"00:00/{self.format_time(self.total_length)}"
            self.duration_label.config(text=duration_str)
            
            self.check_files_loaded()
    
    def load_srt(self):
        self.srt_file = filedialog.askopenfilename(
            title="Select SRT File",
            filetypes=[("SRT Files", "*.srt")]
        )
        if self.srt_file:
            self.srt_label.config(text=os.path.basename(self.srt_file))
            self.parse_srt()
            self.check_files_loaded()
    
    def parse_srt(self):
        """Parse the SRT file and extract subtitles with their timings."""
        self.subtitles = []
        
        if not self.srt_file:
            return
        
        try:
            with open(self.srt_file, 'r', encoding='utf-8') as file:
                content = file.read()
        except UnicodeDecodeError:
            # UTF-8でエラーが出る場合、他のエンコーディングを試す
            try:
                with open(self.srt_file, 'r', encoding='shift-jis') as file:
                    content = file.read()
            except UnicodeDecodeError:
                # それでもダメな場合はLatin-1を試す
                with open(self.srt_file, 'r', encoding='latin-1') as file:
                    content = file.read()
        
        # Split by double newline to get each subtitle block
        subtitle_blocks = re.split(r'\n\n+', content.strip())
        
        for block in subtitle_blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:  # At least 3 lines (number, timing, text)
                subtitle_num = lines[0]
                timing = lines[1]
                text = '\n'.join(lines[2:])  # The rest is subtitle text
                
                # Parse timing
                timing_pattern = r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})'
                match = re.match(timing_pattern, timing)
                
                if match:
                    h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
                    start_time = h1*3600 + m1*60 + s1 + ms1/1000
                    end_time = h2*3600 + m2*60 + s2 + ms2/1000
                    
                    self.subtitles.append({
                        'id': subtitle_num,
                        'start': start_time,
                        'end': end_time,
                        'text': text
                    })
        
        # 時間順にソート
        self.subtitles.sort(key=lambda x: x['start'])
    
    def check_files_loaded(self):
        """Enable play button if both files are loaded."""
        if self.audio_file and self.srt_file:
            self.play_btn.config(state=tk.NORMAL)
        else:
            self.play_btn.config(state=tk.DISABLED)
    
    def play(self):
        """Start playback of audio and subtitle display."""
        if not self.playing:
            if not self.paused:
                # 新規再生
                pygame.mixer.music.load(self.audio_file)
                pygame.mixer.music.play()
                self.current_position = 0.0
                self.paused_position = 0.0
                self.initial_position = 0.0
            else:
                # 一時停止した位置から再開
                # 一時停止位置から開始するようにpygameに指示
                pygame.mixer.music.play(start=self.paused_position)
                
                # GUIの時間表示を一時停止時点の値に即時更新
                time_str = self.format_time(self.paused_position)
                self.time_label.config(text=time_str)
                
                # initial_positionを正しく設定（このスレッドでセット）
                self.initial_position = self.paused_position
                
                # paused状態を解除
                self.paused = False
            
            self.playing = True
            self.play_btn.config(state=tk.DISABLED)
            self.pause_btn.config(state=tk.NORMAL)  # 再生中はPauseボタンを有効化
            self.stop_btn.config(state=tk.NORMAL)
            
            # 前回のスレッドが実行中なら停止フラグを立てる
            if self.subtitle_thread and self.subtitle_thread.is_alive():
                self.stop_thread = True
                self.subtitle_thread.join(timeout=1.0)  # 最大1秒待機
            
            # 停止フラグをリセット
            self.stop_thread = False
            
            # Start the subtitle display thread
            self.subtitle_thread = threading.Thread(target=self.update_subtitles)
            self.subtitle_thread.daemon = True
            self.subtitle_thread.start()
    
    def pause(self):
        """Pause playback."""
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            # 現在のpygameの再生位置を保存
            pos_ms = pygame.mixer.music.get_pos()
            # 負の値になることがあるためチェック
            if pos_ms >= 0:
                # 一時停止した位置を保存（秒単位）
                self.paused_position = pos_ms / 1000.0
                if hasattr(self, 'initial_position'):
                    self.paused_position += self.initial_position
            else:
                # get_posが失敗した場合、現在のcurrent_positionを使用
                self.paused_position = self.current_position
                
            self.paused = True
            self.playing = False
            self.play_btn.config(state=tk.NORMAL)
            self.pause_btn.config(state=tk.DISABLED)  # 一時停止中はPauseボタンを無効化
    
    def stop(self):
        """Stop playback."""
        self.stop_thread = True  # スレッドに停止を通知
        pygame.mixer.music.stop()
        self.playing = False
        self.paused = False
        self.current_position = 0.0
        self.paused_position = 0.0
        self.initial_position = 0.0
        
        # 字幕履歴をクリア
        self.subtitle_history = []
        self.last_subtitle_id = ""
        
        self.play_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.subtitle_display.delete(1.0, tk.END)
        self.time_label.config(text="00:00:00,000")
        self.seek_var.set(0)  # シークバーをリセット
        
        # 時間表示をリセット
        duration_str = f"00:00/{self.format_time(self.total_length)}"
        self.duration_label.config(text=duration_str)
    
    def format_time(self, seconds):
        """秒数を00:00:00,000形式にフォーマット"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds_part = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds:03d}"
    
    def update_subtitles(self):
        """再生位置に基づいて字幕を更新するスレッド"""
        # 字幕同期のための補正値（秒）- 必要に応じて調整
        sync_offset = 0.1
        
        # 前回表示した字幕のテキスト
        last_subtitle_text = ""
        
        # 再生開始時間
        start_time = time.time()
        
        # この時点でself.initial_positionはplayメソッドで設定済み
        # そのまま使用する（ここで上書きしない）
        
        while not self.stop_thread and self.playing:
            if not pygame.mixer.music.get_busy():
                # 再生が終了
                self.root.after(100, self.stop)  # GUIスレッドでstopを呼び出す
                break
            
            # pygameの再生位置を取得（ミリ秒単位）
            pos_ms = pygame.mixer.music.get_pos()
            
            if pos_ms >= 0:
                # ミリ秒を秒に変換し、開始位置を加算
                # 一時停止からの再開時には新しい再生開始時点からの時間になる
                self.current_position = pos_ms / 1000.0 + self.initial_position
            else:
                # get_posが失敗した場合は経過時間を使用
                elapsed = time.time() - start_time
                self.current_position = self.initial_position + elapsed
            
            # 時間表示を更新（GUIスレッドで実行）
            time_str = self.format_time(self.current_position)
            self.root.after(0, lambda s=time_str: self.time_label.config(text=s))
            
            # シークバーの位置を更新
            if hasattr(self, 'total_length') and self.total_length > 0:
                seek_percent = (self.current_position / self.total_length) * 100
                self.root.after(0, lambda p=seek_percent: self.seek_var.set(p))
                
                # 時間表示も更新
                current_str = self.format_time(self.current_position)
                total_str = self.format_time(self.total_length)
                dur_str = f"{current_str}/{total_str}"
                self.root.after(0, lambda s=dur_str: self.duration_label.config(text=s))
            
            # 現在表示すべき字幕を見つける
            current_text = ""
            current_subtitle_id = None
            adjusted_time = self.current_position - sync_offset  # 表示タイミング調整
            
            for subtitle in self.subtitles:
                if subtitle['start'] <= adjusted_time <= subtitle['end']:
                    current_text = subtitle['text']
                    current_subtitle_id = subtitle['id']
                    break
            
            # テキストが変わった場合のみ更新（ちらつき防止）- GUIスレッドで実行
            if current_text != last_subtitle_text:
                self.root.after(0, lambda t=current_text, id=current_subtitle_id: 
                                self.update_subtitle_text(t, id))
                last_subtitle_text = current_text
            
            # CPU使用率を抑えるための短いスリープ
            time.sleep(0.05)
    
    def update_subtitle_text(self, text, subtitle_id=None):
        """GUIスレッドで字幕テキストを更新（スレッドセーフ）
        新しい字幕のみをテキストエリアに追加する
        タイムコード付きで表示する
        """
        # 空のテキストは処理しない
        if not text.strip():
            return
            
        # 新しい字幕の場合
        if subtitle_id and subtitle_id != self.last_subtitle_id:
            # 現在の字幕のタイムコードを取得
            current_timecode = ""
            current_start = 0
            current_end = 0
            
            for subtitle in self.subtitles:
                if subtitle['id'] == subtitle_id:
                    current_start = subtitle['start']
                    current_end = subtitle['end']
                    start_time = self.format_time(current_start)
                    end_time = self.format_time(current_end)
                    current_timecode = f"[{start_time} --> {end_time}]"
                    break
            
            # テキストをタイムコード付きで整形
            display_text = f"{current_timecode}\n{text}"
            
            # 内部履歴に追加（タイムコード付き）
            self.subtitle_history.append(display_text)
            self.last_subtitle_id = subtitle_id
            
            # テキストエリアに新しい字幕のみを追加
            if self.subtitle_display.get(1.0, tk.END).strip():
                # すでにテキストがある場合は、改行を追加してから新しい字幕を追加
                self.subtitle_display.insert(tk.END, "\n\n" + display_text)
            else:
                # テキストエリアが空の場合は、そのまま追加
                self.subtitle_display.insert(tk.END, display_text)
            
            # 自動スクロールが有効ならスクロール
            if self.autoscroll_var.get():
                self.subtitle_display.see(tk.END)
        elif not subtitle_id:
            # 履歴モードでない場合（従来の動作）
            self.subtitle_display.delete(1.0, tk.END)
            self.subtitle_display.insert(tk.END, text)


def main():
    # コマンドライン引数の処理
    parser = argparse.ArgumentParser(description='SRT Player - 音声と字幕を同期再生')
    parser.add_argument('-a', '--audio', help='音声ファイルのパス')
    parser.add_argument('-s', '--srt', help='字幕ファイル(SRT)のパス')
    args = parser.parse_args()
    
    root = tk.Tk()
    # ウィンドウサイズを大きく設定
    root.geometry("800x600")
    app = SRTPlayer(root)
    
    # コマンドライン引数でファイルが指定されていれば読み込む
    if args.audio and os.path.isfile(args.audio):
        app.audio_file = args.audio
        app.audio_label.config(text=os.path.basename(args.audio))
        app.check_files_loaded()
    
    if args.srt and os.path.isfile(args.srt):
        app.srt_file = args.srt
        app.srt_label.config(text=os.path.basename(args.srt))
        app.parse_srt()
        app.check_files_loaded()
    
    root.mainloop()

if __name__ == "__main__":
    main()