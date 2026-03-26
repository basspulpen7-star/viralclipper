from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import subprocess
import os
import threading
import uuid
import time
import shutil

app = Flask(__name__)

# ─── Config (dari environment variable Railway) ───────────────────────────────
UPLOAD_FOLDER = os.environ.get('UPLOAD_DIR', '/tmp/clips')
COOKIE_FILE   = '/app/cookies.txt'
MAX_CLIP_DUR  = int(os.environ.get('MAX_CLIP_DURATION', 90))
JOB_TTL       = int(os.environ.get('JOB_TTL', 3600))   # auto delete 1 jam
PORT          = int(os.environ.get('PORT', 5000))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
jobs = {}
jobs_lock = threading.Lock()

# ─── Whisper check ─────────────────────────────────────────────────────────────
def check_whisper():
    try:
        from faster_whisper import WhisperModel
        return 'faster_whisper'
    except ImportError:
        return None

WHISPER_BACKEND = check_whisper()

# ─── Auto cleanup background thread ──────────────────────────────────────────
def cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        with jobs_lock:
            expired = [jid for jid, j in jobs.items()
                       if now - j.get('created_at', now) > JOB_TTL]
        for jid in expired:
            shutil.rmtree(os.path.join(UPLOAD_FOLDER, jid), ignore_errors=True)
            with jobs_lock:
                jobs.pop(jid, None)

threading.Thread(target=cleanup_loop, daemon=True).start()

# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_video_info(url):
    opts = {'quiet': True, 'no_warnings': True, 'socket_timeout': 30}
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def find_peak_segments(heatmap, duration, top_n=3, clip_duration=60):
    clip_duration = min(clip_duration, MAX_CLIP_DUR)
    if not heatmap:
        positions = [0, max(0, duration//2 - clip_duration//2), max(0, duration - clip_duration)]
        labels    = ['Intro', 'Tengah', 'Outro']
        return [{'start': round(p, 1), 'end': round(min(p+clip_duration, duration), 1),
                 'score': 0.5, 'label': l}
                for p, l in zip(positions[:top_n], labels[:top_n])]

    peaks = []
    for entry in sorted(heatmap, key=lambda x: x.get('value', 0), reverse=True):
        center = (entry['start_time'] + entry.get('end_time', entry['start_time']+5)) / 2
        start  = max(0, center - clip_duration/2)
        end    = min(duration, start + clip_duration)
        start  = max(0, end - clip_duration)
        if not any(not (end <= p['end']+5 or start >= p['start']-5) for p in peaks):
            peaks.append({'start': round(start,1), 'end': round(end,1),
                          'score': round(entry.get('value',0),3),
                          'label': f'Peak #{len(peaks)+1}'})
        if len(peaks) >= top_n:
            break
    return sorted(peaks, key=lambda x: x['start'])

def sec_to_srt(s):
    h,m,sec,ms = int(s//3600), int((s%3600)//60), int(s%60), int((s-int(s))*1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def split_sub(text, n=40):
    if len(text) <= n: return text
    w = text.split(); mid = len(w)//2
    return ' '.join(w[:mid]) + '\n' + ' '.join(w[mid:])

def to_srt(segs):
    lines = []
    for i, s in enumerate(segs, 1):
        lines += [str(i), f"{sec_to_srt(s['start'])} --> {sec_to_srt(s['end'])}", s['text'].strip(), '']
    return '\n'.join(lines)

def transcribe(audio_path, language, model_size):
    if not WHISPER_BACKEND:
        raise RuntimeError("faster-whisper tidak tersedia di server ini.")
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device='cpu', compute_type='int8')
    lang  = None if language == 'auto' else language
    segs, _ = model.transcribe(audio_path, language=lang, vad_filter=True)
    return [{'start': s.start, 'end': s.end, 'text': split_sub(s.text.strip())} for s in segs]

def sub_filter(srt_path, style):
    colors = {
        'yellow': ('&H0000FFFF', '&H00000000'),
        'white':  ('&H00FFFFFF', '&H00000000'),
        'cyan':   ('&H00FFFF00', '&H00000000'),
        'green':  ('&H0000FF00', '&H00000000'),
    }
    pri, out = colors.get(style['color'], colors['yellow'])
    fs = (f"Fontname=Arial,Fontsize={style['fontsize']},"
          f"PrimaryColour={pri},OutlineColour={out},"
          f"BorderStyle=3,Outline=2,Shadow=1,Bold=1,"
          f"Alignment={style['alignment']},MarginV={style['margin_v']}")
    safe = srt_path.replace('\\', '/').replace(':', '\\:')
    return f"subtitles='{safe}':force_style='{fs}'"

# ─── Main processing job ──────────────────────────────────────────────────────
def process_job(job_id, url, clip_duration, top_n, sub_opts):
    job_dir = os.path.join(UPLOAD_FOLDER, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with jobs_lock:
        jobs[job_id].update({'status': 'fetching', 'progress': 8,
                             'message': 'Mengambil info video...'})

    enable_sub   = sub_opts.get('enabled', False)
    sub_lang     = sub_opts.get('language', 'auto')
    sub_model    = sub_opts.get('model', 'small')
    sub_color    = sub_opts.get('color', 'yellow')
    sub_pos      = sub_opts.get('position', 'bottom')
    pos_map      = {'bottom': (2, 40), 'top': (8, 40)}
    alignment, margin_v = pos_map.get(sub_pos, (2, 40))
    style = {'color': sub_color, 'fontsize': 18, 'alignment': alignment, 'margin_v': margin_v}

    try:
        # 1. Info
        info      = get_video_info(url)
        title     = info.get('title', 'Video')
        duration  = info.get('duration', 0)
        heatmap   = info.get('heatmap', [])
        thumbnail = info.get('thumbnail', '')

        with jobs_lock:
            jobs[job_id].update({'title': title, 'duration': duration,
                                 'thumbnail': thumbnail, 'progress': 20,
                                 'message': f'Video: {title}'})

        # 2. Segments
        with jobs_lock:
            jobs[job_id].update({'status': 'analyzing', 'progress': 28,
                                 'message': 'Mendeteksi segmen viral...'})
        segments = find_peak_segments(heatmap, duration, top_n, clip_duration)
        with jobs_lock:
            jobs[job_id].update({'segments': segments, 'heatmap': heatmap,
                                 'progress': 38, 'message': f'{len(segments)} segmen ditemukan'})

        # 3. Download — hemat disk: hanya audio+video yang diperlukan
        with jobs_lock:
            jobs[job_id].update({'status': 'downloading', 'progress': 42,
                                 'message': 'Mendownload video...'})
        dl_opts = {
            'outtmpl'     : os.path.join(job_dir, 'source.%(ext)s'),
            'format'      : 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
            'quiet'       : True, 'no_warnings': True,
        }
        if os.path.exists(COOKIE_FILE):
            dl_opts['cookiefile'] = COOKIE_FILE
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])

        source_file = next(
            (os.path.join(job_dir, f) for f in os.listdir(job_dir) if f.startswith('source.')), None)
        if not source_file:
            raise Exception('Download gagal — source file tidak ditemukan.')

        with jobs_lock:
            jobs[job_id].update({'progress': 55, 'message': 'Download selesai...'})

        # 4. Extract audio sekali (jika subtitle aktif)
        full_audio = None
        if enable_sub:
            if not WHISPER_BACKEND:
                raise RuntimeError("faster-whisper tidak terinstall di server. Matikan fitur subtitle.")
            with jobs_lock:
                jobs[job_id].update({'status': 'transcribing_prep', 'progress': 57,
                                     'message': 'Mengekstrak audio untuk Whisper...'})
            full_audio = os.path.join(job_dir, 'audio_full.wav')
            subprocess.run(['ffmpeg', '-y', '-i', source_file,
                            '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', full_audio],
                           check=True, capture_output=True)

        # 5. Per-clip
        clips_info = []
        n    = len(segments)
        step = max(1, 38 // n)

        for i, seg in enumerate(segments):
            bp = 60 + i * step

            with jobs_lock:
                jobs[job_id].update({'status': 'clipping', 'progress': bp,
                                     'message': f'Memotong clip {i+1}/{n}...'})

            raw_mp4 = os.path.join(job_dir, f'raw_{i+1}.mp4')
            subprocess.run([
                'ffmpeg', '-y',
                '-ss', str(seg['start']), '-to', str(seg['end']),
                '-i', source_file,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '24',
                '-c:a', 'aac', '-b:a', '96k',
                '-vf', ('scale=1080:1920:force_original_aspect_ratio=decrease,'
                        'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black'),
                raw_mp4
            ], check=True, capture_output=True)

            out_mp4  = os.path.join(job_dir, f'clip_{i+1}.mp4')
            srt_path = None

            if enable_sub:
                with jobs_lock:
                    jobs[job_id].update({'status': 'transcribing',
                                         'progress': bp + step//2,
                                         'message': f'Whisper AI transkripsi clip {i+1}/{n}...'})
                clip_wav = os.path.join(job_dir, f'a_{i+1}.wav')
                subprocess.run([
                    'ffmpeg', '-y',
                    '-ss', str(seg['start']), '-to', str(seg['end']),
                    '-i', full_audio, '-ar', '16000', '-ac', '1', clip_wav
                ], check=True, capture_output=True)

                raw_segs = transcribe(clip_wav, sub_lang, sub_model)
                os.remove(clip_wav)

                srt_path = os.path.join(job_dir, f'clip_{i+1}.srt')
                with open(srt_path, 'w', encoding='utf-8') as f:
                    f.write(to_srt(raw_segs))

                with jobs_lock:
                    jobs[job_id].update({'message': f'Burn subtitle clip {i+1}/{n}...'})
                subprocess.run([
                    'ffmpeg', '-y', '-i', raw_mp4,
                    '-vf', sub_filter(srt_path, style),
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', out_mp4
                ], check=True, capture_output=True)
                os.remove(raw_mp4)
            else:
                os.rename(raw_mp4, out_mp4)

            size = os.path.getsize(out_mp4)
            clips_info.append({
                'index': i+1, 'start': seg['start'], 'end': seg['end'],
                'score': seg['score'], 'label': seg['label'],
                'duration': seg['end'] - seg['start'],
                'size_mb': round(size/1024/1024, 2),
                'has_subtitle': enable_sub and srt_path is not None,
                'download_url': f'/download/{job_id}/clip_{i+1}.mp4',
                'srt_url': f'/download/{job_id}/clip_{i+1}.srt' if srt_path else None,
            })

        # Cleanup source & full audio untuk hemat disk
        if os.path.exists(source_file): os.remove(source_file)
        if full_audio and os.path.exists(full_audio): os.remove(full_audio)

        sub_tag = ' + subtitle AI' if enable_sub else ''
        with jobs_lock:
            jobs[job_id].update({
                'status': 'done', 'progress': 100,
                'message': f'Selesai! {len(clips_info)} clips{sub_tag} siap didownload.',
                'clips': clips_info
            })

    except Exception as e:
        with jobs_lock:
            jobs[job_id].update({'status': 'error', 'error': str(e),
                                 'message': f'Error: {str(e)}'})
        # Cleanup on error
        shutil.rmtree(job_dir, ignore_errors=True)


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process', methods=['POST'])
def process():
    data          = request.json or {}
    url           = data.get('url', '').strip()
    clip_duration = min(int(data.get('clip_duration', 60)), MAX_CLIP_DUR)
    top_n         = min(int(data.get('top_n', 3)), 5)
    sub_opts      = data.get('subtitle', {'enabled': False})

    if not url:
        return jsonify({'error': 'URL tidak boleh kosong'}), 400

    # Batasi concurrent jobs
    with jobs_lock:
        active = sum(1 for j in jobs.values() if j['status'] not in ('done', 'error'))
        if active >= 5:
            return jsonify({'error': 'Server sibuk, coba lagi sebentar.'}), 429

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {'status': 'queued', 'progress': 0, 'clips': [],
                        'error': None, 'title': '', 'created_at': time.time()}

    threading.Thread(target=process_job,
                     args=(job_id, url, clip_duration, top_n, sub_opts),
                     daemon=True).start()
    return jsonify({'job_id': job_id})

@app.route('/api/status/<job_id>')
def status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job tidak ditemukan atau sudah expired'}), 404
    return jsonify(job)

@app.route('/api/whisper_status')
def whisper_status():
    return jsonify({'available': WHISPER_BACKEND is not None, 'backend': WHISPER_BACKEND})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'whisper': WHISPER_BACKEND})

@app.route('/download/<job_id>/<filename>')
def download(job_id, filename):
    # Security: only allow safe filenames
    if '..' in filename or '/' in filename:
        return 'Invalid filename', 400
    path = os.path.join(UPLOAD_FOLDER, job_id, filename)
    if not os.path.exists(path):
        return 'File tidak ditemukan atau sudah expired', 404
    return send_file(path, as_attachment=True, download_name=filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
