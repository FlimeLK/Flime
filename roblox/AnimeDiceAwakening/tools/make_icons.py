# Generates the sticker-style icon pack (SVG) for Anime Dice: Awakening.
# Render to 512x512 PNG with any browser or Inkscape; ready PNGs are in assets/icons/
O = "#1b1030"   # outline
W = 10           # outline width

def grad(id, top, bottom):
    return f'<linearGradient id="{id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'

def shine(x, y, w, h, r=0):
    return f'<ellipse cx="{x}" cy="{y}" rx="{w}" ry="{h}" fill="#fff" opacity=".45" transform="rotate({r} {x} {y})"/>'

ICONS = {}

ICONS["Roll"] = f'''<defs>{grad("t","#ffffff","#e6e0ff")}{grad("l","#d9d0ff","#a796f0")}{grad("r","#b9a8ff","#7d63e0")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M128 28 L222 76 L128 124 L34 76 Z" fill="url(#t)"/>
<path d="M34 76 L128 124 L128 230 L34 182 Z" fill="url(#l)"/>
<path d="M222 76 L128 124 L128 230 L222 182 Z" fill="url(#r)"/></g>
<g fill="#ff3d6e" stroke="{O}" stroke-width="4"><ellipse cx="128" cy="76" rx="17" ry="9"/></g>
<g fill="#3b2a8a"><ellipse cx="62" cy="118" rx="10" ry="13"/><ellipse cx="100" cy="186" rx="10" ry="13"/><ellipse cx="81" cy="152" rx="10" ry="13"/>
<ellipse cx="156" cy="120" rx="10" ry="13"/><ellipse cx="194" cy="102" rx="10" ry="13"/><ellipse cx="156" cy="190" rx="10" ry="13"/><ellipse cx="194" cy="172" rx="10" ry="13"/></g>
{shine(92,62,28,9,-27)}'''

ICONS["Backpack"] = f'''<defs>{grad("b","#ff7b6b","#d8323c")}{grad("p","#ff9f8f","#e5484f")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round" stroke-linecap="round">
<path d="M96 52 Q128 14 160 52" fill="none"/>
<rect x="44" y="52" width="168" height="182" rx="46" fill="url(#b)"/>
<path d="M44 110 Q128 150 212 110 L212 98 Q212 52 166 52 L90 52 Q44 52 44 98 Z" fill="url(#p)"/>
<rect x="82" y="160" width="92" height="56" rx="18" fill="url(#p)"/>
<rect x="116" y="118" width="24" height="28" rx="6" fill="#ffd34d"/></g>
{shine(96,74,30,10,-10)}'''

ICONS["Team"] = f'''<defs>{grad("s","#ffffff","#a9bde0")}{grad("h","#ffd75a","#e89a1c")}</defs>
<g stroke="{O}" stroke-width="8" stroke-linejoin="round">
<g transform="rotate(-45 128 128)">
<path d="M112 30 L128 10 L144 30 L144 160 L112 160 Z" fill="url(#s)"/>
<rect x="88" y="158" width="80" height="18" rx="8" fill="url(#h)"/>
<rect x="117" y="176" width="22" height="44" rx="6" fill="#7a4a2a"/>
<circle cx="128" cy="232" r="13" fill="url(#h)"/></g>
<g transform="rotate(45 128 128)">
<path d="M112 30 L128 10 L144 30 L144 160 L112 160 Z" fill="url(#s)"/>
<rect x="88" y="158" width="80" height="18" rx="8" fill="url(#h)"/>
<rect x="117" y="176" width="22" height="44" rx="6" fill="#7a4a2a"/>
<circle cx="128" cy="232" r="13" fill="url(#h)"/></g></g>
<path d="M120 36 L120 150" stroke="#fff" stroke-width="5" opacity=".7" transform="rotate(45 128 128)"/>'''

ICONS["Upgrades"] = f'''<defs>{grad("g","#8dff7a","#22b33a")}</defs>
<path d="M128 22 L230 130 L172 130 L172 230 L84 230 L84 130 L26 130 Z" fill="url(#g)" stroke="{O}" stroke-width="{W}" stroke-linejoin="round"/>
{shine(104,92,34,12,-45)}'''

ICONS["Quests"] = f'''<defs>{grad("p","#fff3d1","#f2c983")}{grad("r","#f7d79a","#c8893a")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<rect x="56" y="48" width="144" height="168" rx="10" fill="url(#p)"/>
<rect x="40" y="30" width="176" height="40" rx="20" fill="url(#r)"/>
<rect x="40" y="196" width="176" height="40" rx="20" fill="url(#r)"/></g>
<g stroke="#b07b3a" stroke-width="9" stroke-linecap="round"><path d="M84 100 H172"/><path d="M84 128 H172"/><path d="M84 156 H148"/></g>
<circle cx="176" cy="176" r="18" fill="#ff4b5c" stroke="{O}" stroke-width="6"/>'''

ICONS["Rebirth"] = f'''<defs>{grad("a","#ff7a7a","#d61f3a")}{grad("b","#ffffff","#cfd8ff")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M64 128 A64 64 0 0 1 182 94 L204 70 L214 150 L136 140 L160 118 A34 34 0 0 0 98 128 Z" fill="url(#a)"/>
<path d="M192 128 A64 64 0 0 1 74 162 L52 186 L42 106 L120 116 L96 138 A34 34 0 0 0 158 128 Z" fill="url(#b)"/></g>
{shine(100,74,26,8,-30)}'''

ICONS["Index"] = f'''<defs>{grad("c","#6fb2ff","#2a5fe0")}{grad("p","#ffffff","#dfe6f5")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M40 70 L128 46 L216 70 L216 214 L128 236 L40 214 Z" fill="url(#c)"/>
<path d="M56 74 L128 58 L128 216 L56 200 Z" fill="url(#p)"/>
<path d="M200 74 L128 58 L128 216 L200 200 Z" fill="url(#p)"/></g>
<g stroke="#9db0d8" stroke-width="7" stroke-linecap="round"><path d="M72 102 L112 94"/><path d="M72 128 L112 120"/><path d="M72 154 L112 146"/>
<path d="M144 94 L184 102"/><path d="M144 120 L184 128"/><path d="M144 146 L184 154"/></g>
<path d="M150 46 L150 98 L164 86 L178 98 L178 50" fill="#ff4b5c" stroke="{O}" stroke-width="6" stroke-linejoin="round"/>'''

ICONS["Worlds"] = f'''<defs><radialGradient id="o" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#8fd8ff"/><stop offset="1" stop-color="#1f6fe0"/></radialGradient>{grad("l","#8dff7a","#2aa548")}</defs>
<circle cx="128" cy="128" r="102" fill="url(#o)" stroke="{O}" stroke-width="{W}"/>
<path d="M70 70 Q96 52 118 64 Q132 84 112 96 Q92 104 98 126 Q90 146 70 134 Q52 110 70 70 Z M140 120 Q170 108 192 126 Q200 160 176 184 Q150 196 142 170 Q150 150 140 120 Z M150 50 Q176 52 188 72 Q170 82 152 70 Z" fill="url(#l)" stroke="{O}" stroke-width="6" stroke-linejoin="round"/>
{shine(92,70,30,14,-35)}'''

ICONS["Home"] = f'''<defs>{grad("r","#ff8a6b","#d8322f")}{grad("w","#ffffff","#d6e2ff")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<rect x="60" y="112" width="136" height="118" rx="8" fill="url(#w)"/>
<path d="M24 128 L128 34 L232 128 L204 128 L128 62 L52 128 Z" fill="url(#r)"/>
<rect x="108" y="160" width="40" height="70" rx="6" fill="#7a4a2a"/>
<rect x="160" y="40" width="26" height="46" fill="url(#r)"/></g>
<rect x="74" y="136" width="26" height="24" rx="4" fill="#6fc4ff" stroke="{O}" stroke-width="6"/>'''

ICONS["Shop"] = f'''<defs>{grad("b","#ff5b7c","#c01f4a")}{grad("l","#ff8aa2","#e23a62")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M44 108 L212 108 L196 226 L60 226 Z" fill="url(#b)"/>
<path d="M30 84 L226 84 L226 112 L30 112 Z" fill="url(#l)"/>
<path d="M84 84 Q84 30 128 30 Q172 30 172 84" fill="none"/>
<path d="M104 140 L104 194 M152 140 L152 194" stroke="#ffffff" stroke-width="10" stroke-linecap="round"/></g>
{shine(94,96,40,7,0)}'''

ICONS["Settings"] = f'''<defs>{grad("g","#e6e9f5","#8c93ad")}</defs>
<path d="M112 22 H144 L150 52 L172 61 L197 43 L220 66 L202 91 L211 113 L240 119 V151 L211 157 L202 179 L220 204 L197 227 L172 209 L150 218 L144 248 H112 L106 218 L84 209 L59 227 L36 204 L54 179 L45 157 L16 151 V119 L45 113 L54 91 L36 66 L59 43 L84 61 L106 52 Z" transform="translate(0 -7)" fill="url(#g)" stroke="{O}" stroke-width="{W}" stroke-linejoin="round"/>
<circle cx="128" cy="128" r="34" fill="#4b4f66" stroke="{O}" stroke-width="{W}"/>'''

ICONS["Coin"] = f'''<defs><radialGradient id="c" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff2a0"/><stop offset="1" stop-color="#f0a818"/></radialGradient></defs>
<circle cx="128" cy="128" r="104" fill="url(#c)" stroke="{O}" stroke-width="{W}"/>
<circle cx="128" cy="128" r="74" fill="none" stroke="#d48a10" stroke-width="10"/>
<path d="M128 74 L143 110 L182 112 L152 136 L162 174 L128 152 L94 174 L104 136 L74 112 L113 110 Z" fill="#ffe36a" stroke="#c07a0c" stroke-width="7" stroke-linejoin="round"/>
{shine(92,72,30,12,-35)}'''

ICONS["Crystal"] = f'''<defs>{grad("a","#e6b8ff","#a03cff")}{grad("b","#c27bff","#6a17d6")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M68 40 L188 40 L236 98 L128 230 L20 98 Z" fill="url(#b)"/>
<path d="M20 98 L236 98 M68 40 L96 98 L128 40 L160 98 L188 40 M96 98 L128 230 L160 98" fill="none" stroke-width="6"/></g>
<path d="M76 50 L120 50 L96 92 Z" fill="#fff" opacity=".5"/>'''

LEAF = "M128 124 Q96 124 84 96 Q72 62 100 56 Q120 54 128 76 Q136 54 156 56 Q184 62 172 96 Q160 124 128 124 Z"
ICONS["Luck"] = f'''<defs>{grad("g","#9dff8a","#26a83c")}</defs>
<path d="M132 136 Q156 196 132 244" fill="none" stroke="{O}" stroke-width="16" stroke-linecap="round"/>
<path d="M132 136 Q156 196 132 244" fill="none" stroke="#2f8f3a" stroke-width="7" stroke-linecap="round"/>
<g fill="url(#g)" stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="{LEAF}"/><path d="{LEAF}" transform="rotate(90 128 128)"/><path d="{LEAF}" transform="rotate(180 128 128)"/><path d="{LEAF}" transform="rotate(270 128 128)"/></g>
<circle cx="128" cy="128" r="10" fill="#26a83c"/>
{shine(104,78,14,6,-30)}{shine(178,104,14,6,60)}'''

ICONS["Auto"] = f'''<defs>{grad("a","#ffffff","#cfe1ff")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M56 120 A72 72 0 0 1 186 84 L210 60 L218 144 L136 136 L162 110 A40 40 0 0 0 92 124 Z" fill="url(#a)"/>
<path d="M200 136 A72 72 0 0 1 70 172 L46 196 L38 112 L120 120 L94 146 A40 40 0 0 0 164 132 Z" fill="url(#a)"/></g>'''

ICONS["Lock"] = f'''<defs>{grad("g","#ffe27a","#e8a51c")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M80 116 V82 A48 48 0 0 1 176 82 V116" fill="none" stroke-width="30"/>
<path d="M80 116 V82 A48 48 0 0 1 176 82 V116" fill="none" stroke="#c3c9dc" stroke-width="12"/>
<rect x="48" y="112" width="160" height="120" rx="22" fill="url(#g)"/>
<path d="M128 150 V188" stroke-width="16" stroke-linecap="round"/></g>
{shine(96,130,34,8,0)}'''

ICONS["LuckPotion"] = f'''<defs>{grad("l","#9dff8a","#1f9e3a")}{grad("g","#ffffff","#d9f2ff")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<rect x="104" y="20" width="48" height="30" rx="8" fill="#b07a46"/>
<path d="M108 50 H148 V92 Q216 120 210 180 Q204 236 128 236 Q52 236 46 180 Q40 120 108 92 Z" fill="url(#g)"/>
<path d="M58 160 Q90 148 128 162 Q166 176 198 160 Q200 226 128 226 Q56 226 58 160 Z" fill="url(#l)" stroke-width="6"/></g>
<text x="128" y="214" font-size="52" text-anchor="middle">🍀</text>{shine(92,124,14,26,20)}'''

ICONS["CoinPotion"] = ICONS["LuckPotion"].replace("#9dff8a","#fff08a").replace("#1f9e3a","#e0a114").replace("🍀","💰")

ICONS["Slots"] = f'''<defs>{grad("b","#ff9a6b","#d8562f")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round" fill="url(#b)">
<rect x="24" y="44" width="100" height="52" rx="8"/><rect x="132" y="44" width="100" height="52" rx="8"/>
<rect x="24" y="104" width="46" height="52" rx="8"/><rect x="78" y="104" width="100" height="52" rx="8"/><rect x="186" y="104" width="46" height="52" rx="8"/>
<rect x="24" y="164" width="100" height="52" rx="8"/><rect x="132" y="164" width="100" height="52" rx="8"/></g>
<circle cx="204" cy="206" r="32" fill="#46d25a" stroke="{O}" stroke-width="8"/><path d="M204 188 V224 M186 206 H222" stroke="#fff" stroke-width="10" stroke-linecap="round"/>'''

ICONS["Income"] = f'''<defs>{grad("b","#ffe08a","#d89a1c")}</defs>
<g stroke="{O}" stroke-width="{W}" stroke-linejoin="round">
<path d="M96 60 L80 30 Q128 14 176 30 L160 60 Z" fill="url(#b)"/>
<path d="M96 60 H160 Q236 120 220 186 Q206 236 128 236 Q50 236 36 186 Q20 120 96 60 Z" fill="url(#b)"/>
<path d="M90 62 Q128 78 166 62" fill="none" stroke-width="8"/></g>
<text x="128" y="190" font-family="Fredoka, sans-serif" font-size="96" font-weight="bold" text-anchor="middle" fill="#2fa44a" stroke="{O}" stroke-width="5">$</text>
{shine(86,124,14,30,20)}'''

ICONS["BigBag"] = ICONS["Backpack"].replace("#ff7b6b","#b98aff").replace("#d8323c","#7a3ce0").replace("#ff9f8f","#d2b3ff").replace("#e5484f","#9054f0")

import pathlib
out = pathlib.Path("svg"); out.mkdir(exist_ok=True)
for name, body in ICONS.items():
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">{body}</svg>'
    (out / f"{name}.svg").write_text(svg)
html = '<html><head><meta charset="utf-8"><style>@font-face{font-family:Fredoka;src:url(../mock/fredoka.ttf)}body{margin:0;background:#2a2a34;display:flex;flex-wrap:wrap;width:1320px;font-family:Fredoka}div{width:220px;text-align:center;color:#fff;padding:6px 0}img{width:160px;height:160px}</style></head><body>'
html += "".join(f'<div><img src="svg/{n}.svg"><br>{n}</div>' for n in ICONS)
pathlib.Path("sheet.html").write_text(html + "</body></html>")
print(len(ICONS), "icons")
