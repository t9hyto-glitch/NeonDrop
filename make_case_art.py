"""Генерує SVG-картинки кейсів у static/cases/. Запуск: python make_case_art.py"""
import os
CASES = [("daily", "FREE DAILY", "#3be08a"), ("budget", "BUDGET BOX", "#9aa0a6"), ("sand", "DESERT RUN", "#e0a63b"), ("smg", "SMG STORM", "#19f3ff"),
         ("pistol", "PISTOL PARTY", "#ff6b6b"), ("heavy", "HEAVY METAL", "#a1887f"), ("rifle", "RIFLE RUSH", "#4b69ff"), ("awp", "AWP LEGENDS", "#8847ff"),
         ("redline", "RED ALERT", "#eb4b4b"), ("mix", "NEON MIX", "#ff2bd6"), ("knife", "BLADE VAULT", "#d32ce6"), ("gloves", "GLOVE LOCKER", "#2dd4bf"),
         ("karambit", "KARAMBIT CLUB", "#ffd700"), ("butterfly", "BUTTERFLY EFFECT", "#fb923c"), ("dragon", "DRAGON HOARD", "#ef4444"), ("elite", "ELITE VAULT", "#f5c542")]
EMB = {
 "daily": '<rect x="12" y="38" width="66" height="44" rx="4"/><rect x="8" y="26" width="74" height="16" rx="4"/><rect x="39" y="26" width="12" height="56" fill="{a}"/><path d="M45 26C28 2 8 14 28 26M45 26C62 2 82 14 62 26" fill="none" stroke="#fff" stroke-width="6"/>',
 "budget": '<ellipse cx="45" cy="70" rx="32" ry="11"/><ellipse cx="45" cy="52" rx="32" ry="11" fill-opacity=".85"/><ellipse cx="45" cy="34" rx="32" ry="11"/><text x="45" y="41" font-size="20" font-weight="700" text-anchor="middle" fill="{a}">$</text>',
 "sand": '<circle cx="45" cy="30" r="17"/><path d="M0 84Q24 48 46 68T90 60V90H0Z"/><path d="M0 84Q24 48 46 68T90 60" fill="none" stroke="{a}" stroke-width="3"/>',
 "smg": '<path d="M52 2L16 52H40L30 88L76 34H52Z"/>',
 "pistol": '<path d="M6 26H64L70 18H84V48H66L60 58L54 84H34L40 58H22L6 44Z"/><rect x="62" y="30" width="14" height="6" fill="{a}"/>',
 "heavy": '<path d="M45 4L82 18V46C82 68 64 80 45 88C26 80 8 68 8 46V18Z"/><path d="M45 18L68 27V46C68 60 57 68 45 74Z" fill="{a}"/>',
 "rifle": '<path d="M2 42H22L28 32H56V38H88V48H58L54 54H42L38 76H26L30 54H2Z"/><rect x="60" y="30" width="10" height="6" fill="{a}"/>',
 "awp": '<circle cx="45" cy="45" r="32" fill="none" stroke="#fff" stroke-width="7"/><path d="M45 2V26M45 64V88M2 45H26M64 45H88" stroke="#fff" stroke-width="6"/><circle cx="45" cy="45" r="6" fill="{a}"/>',
 "redline": '<path d="M45 2C58 22 80 34 74 58C72 74 60 88 45 88C30 88 16 76 18 56C20 44 30 40 33 26C40 36 46 30 45 2Z"/><path d="M45 44C52 54 60 58 57 70C55 78 50 82 45 82C38 82 32 76 33 68C34 60 42 58 45 44Z" fill="{a}"/>',
 "mix": '<path d="M45 4L54 36L86 45L54 54L45 86L36 54L4 45L36 36Z"/><path d="M72 6L75 16L85 19L75 22L72 32L69 22L59 19L69 16Z"/>',
 "knife": '<path d="M12 80L58 12Q76 6 82 22L42 72Z"/><path d="M8 84L24 68L34 78L18 90Z" fill="{a}"/>',
 "gloves": '<rect x="20" y="44" width="50" height="40" rx="10"/><rect x="20" y="10" width="11" height="42" rx="5"/><rect x="33" y="4" width="11" height="48" rx="5"/><rect x="46" y="6" width="11" height="46" rx="5"/><rect x="59" y="14" width="11" height="38" rx="5"/><rect x="8" y="40" width="26" height="12" rx="6" transform="rotate(35 14 46)"/><rect x="20" y="72" width="50" height="8" fill="{a}"/>',
 "karambit": '<path d="M24 86C8 44 38 6 84 10C60 20 48 40 54 60C42 54 36 66 40 86Z"/><circle cx="32" cy="72" r="6" fill="{a}"/>',
 "butterfly": '<path d="M45 46C22 4 2 18 14 46C4 64 22 82 45 54ZM45 46C68 4 88 18 76 46C86 64 68 82 45 54Z"/><rect x="42" y="22" width="6" height="52" rx="3" fill="{a}"/>',
 "dragon": '<path d="M16 30L6 4L34 22ZM74 30L84 4L56 22Z"/><ellipse cx="45" cy="52" rx="38" ry="24"/><ellipse cx="45" cy="52" rx="7" ry="20" fill="{a}"/>',
 "elite": '<path d="M6 72L12 24L32 46L45 12L58 46L78 24L84 72Z"/><rect x="6" y="74" width="78" height="10" rx="3" fill="{a}"/>',
}


def shade(h, f):
    r, g, b = [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(x * f))) for x in (r, g, b))


def make(cid, name, k):
    d, l, a = shade(k, .35), shade(k, .75), shade(k, .3)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320">
<defs>
<radialGradient id="g"><stop offset="0" stop-color="{k}" stop-opacity=".55"/><stop offset="1" stop-color="{k}" stop-opacity="0"/></radialGradient>
<linearGradient id="L" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{l}"/><stop offset="1" stop-color="{d}"/></linearGradient>
<linearGradient id="R" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{k}"/><stop offset="1" stop-color="{shade(k, .45)}"/></linearGradient>
<linearGradient id="T" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset="1" stop-color="{k}"/></linearGradient>
<linearGradient id="M" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f4f4f4"/><stop offset="1" stop-color="#5b5f66"/></linearGradient>
<linearGradient id="B" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<circle cx="160" cy="160" r="152" fill="url(#g)"/>
<polygon points="135,6 185,6 252,150 68,150" fill="url(#B)" opacity=".3"/>
<ellipse cx="160" cy="298" rx="98" ry="12" fill="#000" opacity=".4"/>
<polygon points="52,105 160,160 160,285 52,230" fill="url(#L)"/>
<polygon points="268,105 160,160 160,285 268,230" fill="url(#R)"/>
<polygon points="160,50 268,105 160,160 52,105" fill="url(#T)"/>
<path d="M106 77L214 132M214 77L106 132" stroke="{d}" stroke-opacity=".35" stroke-width="7"/>
<path d="M52 105L160 160L268 105M160 160V285M52 230L160 285L268 230M52 105V230M268 105V230" stroke="url(#M)" stroke-width="8" fill="none" stroke-linejoin="round"/>
<g fill="#fff" stroke="#444" stroke-width="1"><circle cx="160" cy="176" r="4"/><circle cx="160" cy="268" r="4"/><circle cx="60" cy="118" r="4"/><circle cx="260" cy="118" r="4"/></g>
<g transform="translate(64,138) skewY(27) scale(.98)" fill="#fff">{EMB[cid].format(a=a)}</g>
<g transform="translate(168,208) skewY(-27)"><rect width="92" height="24" rx="4" fill="#06060c" fill-opacity=".8" stroke="{k}" stroke-width="1.5"/><text x="46" y="16" font-family="Arial,Helvetica,sans-serif" font-size="10" font-weight="700" fill="#fff" text-anchor="middle" textLength="78" lengthAdjust="spacingAndGlyphs">{name}</text></g>
</svg>'''


os.makedirs("static/cases", exist_ok=True)
for cid, name, k in CASES:
    open(f"static/cases/{cid}.svg", "w", encoding="utf-8").write(make(cid, name, k))
print("Готово:", len(CASES), "картинок у static/cases/")
