path = r'c:\Users\n\Documents\hotshort\templates\results_new.html'
with open(path, 'rb') as f:
    data = f.read()

old = (
    b'              <select id="exportFormat_${clipIdNum}" class="form-select bg-dark text-white border-secondary mb-2" style="max-width: 200px; display: inline-block;">\r\n'
    b'                <option value="tiktok">TikTok (9:16 \xe2\x80\xa2 60s \xe2\x80\xa2 30fps)</option>\r\n'
    b'                <option value="instagram">Instagram Reel (9:16 \xe2\x80\xa2 90s \xe2\x80\xa2 30fps)</option>\r\n'
    b'                <option value="shorts">YouTube Shorts (9:16 \xe2\x80\xa2 60s \xe2\x80\xa2 60fps)</option>\r\n'
    b'              </select>'
)

styled = (
    b'background:rgba(255,210,120,0.06);'
    b'color:rgba(255,210,120,0.85);'
    b'border:1px solid rgba(255,210,120,0.25);'
    b'border-radius:8px;'
    b'padding:6px 10px;'
    b'font-size:0.8rem;'
    b'font-weight:600;'
    b'cursor:pointer;'
    b'outline:none;'
    b'width:100%;'
    b'transition:border-color 0.2s;'
)

new = (
    b'              <select id="exportFormat_${clipIdNum}" style="' + styled + b'">\r\n'
    b'                <option value="tiktok" style="background:#1a1a1a">TikTok (9:16 \xe2\x80\xa2 60s \xe2\x80\xa2 30fps)</option>\r\n'
    b'                <option value="instagram" style="background:#1a1a1a">Instagram Reel (9:16 \xe2\x80\xa2 90s \xe2\x80\xa2 30fps)</option>\r\n'
    b'                <option value="shorts" style="background:#1a1a1a">YouTube Shorts (9:16 \xe2\x80\xa2 60s \xe2\x80\xa2 60fps)</option>\r\n'
    b'              </select>'
)

if old not in data:
    print('OLD NOT FOUND — dumping context:')
    idx = data.find(b'exportFormat_')
    print(repr(data[idx-30:idx+200]))
else:
    data = data.replace(old, new, 1)
    with open(path, 'wb') as f:
        f.write(data)
    print('SELECT STYLED OK')
