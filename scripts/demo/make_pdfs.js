// Tạo PDF mẫu tiếng Nhật (nội dung tự viết, KHÔNG phải tài liệu MHLW) để test UI.
// Chạy: NODE_PATH=$(npm root -g) node scripts/demo/make_pdfs.js out/demo
const { chromium } = require("playwright");
const fs = require("fs");
const out = process.argv[2] || "out/demo";
fs.mkdirSync(out, { recursive: true });

const css = `body{font-family:"Noto Sans CJK JP","WenQuanYi Zen Hei","Hiragino Sans",sans-serif;font-size:10.5pt;margin:0;color:#111}
section{height:270mm;padding:12mm 16mm;box-sizing:border-box;page-break-after:always;position:relative}
.hd{font-size:8.5pt;color:#555;border-bottom:1px solid #999;margin-bottom:5mm;display:flex;justify-content:space-between}
.ft{position:absolute;bottom:8mm;left:0;right:0;text-align:center;font-size:9pt}
h2{font-size:13pt;margin:3mm 0}h3{font-size:11pt;margin:3mm 0}
p{margin:1.6mm 0;line-height:1.65}
table{border-collapse:collapse;width:100%;margin:3mm 0}td,th{border:1px solid #333;padding:1.6mm;font-size:9.5pt}
.logo{position:absolute;top:10mm;right:16mm;width:14mm;height:14mm;border-radius:50%;background:#0f766e;color:#fff;font-size:7pt;display:flex;align-items:center;justify-content:center}
.stamp{display:inline-block;border:2px solid #c00;color:#c00;border-radius:50%;width:16mm;height:16mm;text-align:center;line-height:16mm;font-size:9pt;transform:rotate(-12deg)}`;

const sec = (title, no, body, logo) =>
  `<section>${logo ? '<div class="logo">SAMPLE</div>' : ""}<div class="hd"><span>${title}</span><span>サンプル資料</span></div>${body}<div class="ft">- ${no} -</div></section>`;
const long = (s, n) => Array.from({ length: n }, () => s).join("");

const docs = {
  "akahon_sample_536-543.pdf": [
    ["歯科診療報酬点数表（サンプル）", 536, `<h2>M015-2 CAD/CAM冠（1歯につき）</h2>
<p>1 CAD/CAM冠用材料(Ⅲ)を使用した場合 1,200点</p><p>2 1以外の場合 1,000点</p>
<p>注1 区分番号M015-2に掲げるCAD/CAM冠は、別に厚生労働大臣が定める施設基準に適合しているものとして地方厚生局長等に届け出た保険医療機関において、歯冠補綴物の設計・製作に要するコンピュータ支援設計・製造ユニットを用いて、歯冠補綴物を設計・製作し、装着した場合に限り算定する。</p>
<p>ただし、大臼歯に対しては、別に定める場合に限り算定できる。</p>
<p>注2 CAD/CAM冠用材料の費用は、所定点数に含まれない。</p>`, true],
    ["歯科診療報酬点数表（サンプル）", 537, `<h2>M016 乳歯冠（1歯につき）</h2><p>1 乳歯金属冠の場合 200点</p><p>2 1以外の場合 390点</p>
<table><tr><th rowspan="2">区分</th><th colspan="2">点数</th><th rowspan="2">備考</th></tr><tr><th>前歯</th><th>臼歯</th></tr>
<tr><td>乳歯金属冠</td><td>200点</td><td>200点</td><td>既製品を含む</td></tr>
<tr><td>その他</td><td>390点</td><td>390点</td><td>—</td></tr></table>
<p>なお、乳歯冠の装着に係る費用は所定点数に含まれる。</p>`],
    ["歯科診療報酬点数表（サンプル）", 538, `<h2>M017 ポストクラウン（1歯につき）</h2><p>1 前歯 1,200点</p><p>2 小臼歯 1,100点</p>
<p>注 ポストクラウンは、${long("根管処置を行った歯に対して、支台築造と歯冠補綴を一体として製作した場合に算定するものであり、", 4)}その製作に当たっては</p>`],
    ["歯科診療報酬点数表（サンプル）", 539, `<p>支台築造の費用を別に算定することはできない。</p>
<h2>M018 有床義歯（1床につき）</h2><p>1 局部義歯</p>
<table><tr><th>区分</th><th>点数</th></tr><tr><td>イ 1歯から4歯まで</td><td>594点</td></tr><tr><td>ロ 5歯から8歯まで</td><td>732点</td></tr>
<tr><td>ハ 9歯から11歯まで</td><td>972点</td></tr><tr><td>ニ 12歯から14歯まで</td><td>1,410点</td></tr>
${Array.from({ length: 10 }, (_, i) => `<tr><td>（参考${i + 1}）区分の例示</td><td>—</td></tr>`).join("")}</table>`],
    ["歯科診療報酬点数表（サンプル）", 540, `<table><tr><th>区分</th><th>点数</th></tr><tr><td>2 総義歯</td><td>2,420点</td></tr><tr><td>（総義歯の修理）</td><td>234点</td></tr></table>
<p>注1 有床義歯の製作に当たっては、咬合採得を行った上で製作すること。</p>
<p>注2 この場合において、人工歯の費用は別に算定する。</p>`],
    ["歯科診療報酬点数表（サンプル）", 541, `<h2>算定の流れ（参考図）</h2>
<svg width="560" height="330" viewBox="0 0 560 330" font-size="13" font-family="WenQuanYi Zen Hei">
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z"/></marker></defs>
<rect x="190" y="10" width="180" height="44" rx="8" fill="#e0f2f1" stroke="#0f766e"/><text x="280" y="38" text-anchor="middle">初診・検査</text>
<rect x="190" y="110" width="180" height="44" rx="8" fill="#fff7ed" stroke="#c2410c"/><text x="280" y="138" text-anchor="middle">施設基準の届出あり？</text>
<rect x="40" y="220" width="180" height="44" rx="8" fill="#ecfdf5" stroke="#15803d"/><text x="130" y="248" text-anchor="middle">M015-2 を算定</text>
<rect x="340" y="220" width="180" height="44" rx="8" fill="#fef2f2" stroke="#b91c1c"/><text x="430" y="248" text-anchor="middle">算定不可</text>
<line x1="280" y1="54" x2="280" y2="108" stroke="#333" marker-end="url(#a)"/><line x1="240" y1="154" x2="140" y2="218" stroke="#333" marker-end="url(#a)"/>
<line x1="320" y1="154" x2="420" y2="218" stroke="#333" marker-end="url(#a)"/><text x="170" y="190">はい</text><text x="370" y="190">いいえ</text></svg>
<p>図は算定可否の判断の流れを示したものである。</p><p style="text-align:right"><span class="stamp">確認</span></p>`],
    ["歯科診療報酬点数表（サンプル）", 542, `<h2>I011 歯周基本治療</h2><p>1 スケーリング・ルートプレーニング</p>
<p>イ 前歯 60点</p><p>ロ 小臼歯 64点</p><p>ハ 大臼歯 72点</p>
<p>注1 1口腔単位で実施した場合は、所定点数を算定する。</p>
<p>注2 同一部位に2回以上同一の区分に係る歯周基本治療を行った場合、2回目以降の費用は、所定点数の100分の50に相当する点数により算定する。</p>`],
    ["歯科診療報酬点数表（サンプル）", 543, `<h2>A000 初診料</h2><p>1 歯科初診料 267点</p><p>2 地域歯科診療支援病院歯科初診料 291点</p>
<p>注1 1については、歯科外来診療における院内感染防止対策につき別に厚生労働大臣が定める施設基準に適合しているものとして地方厚生局長等に届け出た保険医療機関において、初診を行った場合に算定する。</p>
<p>この場合において、当該届出を行っていない保険医療機関については、所定点数から10点を減算する。</p>`],
  ],
  "midorihon_sample_372-375.pdf": [
    ["留意事項通知（サンプル）", 372, `<h2>区分番号「B000-4」歯科疾患管理料</h2><p>(1) 歯科疾患管理料は、継続的な歯科疾患の管理が必要な患者に対し、管理計画を作成して、その内容について説明を行った場合に算定する。</p><p>(2) 初診日の属する月から起算して2月以内に1回に限り算定する。</p><p>ただし、再初診の場合はこの限りではない。</p>`, true],
    ["留意事項通知（サンプル）", 373, `<h2>区分番号「B000-6」周術期等口腔機能管理料(Ⅰ)</h2><p>(1) がん等に係る手術を実施する患者の口腔機能を管理するため、計画に基づき管理を行った場合に算定する。</p><p>(2) 手術前は1回に限り、手術後は手術を行った日の属する月から起算して3月以内に3回に限り算定する。</p>`],
    ["留意事項通知（サンプル）", 374, `<h2>区分番号「B001-2」歯科衛生実地指導料</h2><p>(1) 歯科衛生士が直接15分以上の実地指導を行った場合に算定する。</p>
<table><tr><th rowspan="2">区分</th><th colspan="2">点数</th></tr><tr><th>月1回目</th><th>月2回目</th></tr><tr><td>実地指導料1</td><td>80点</td><td>—</td></tr><tr><td>実地指導料2</td><td>100点</td><td>—</td></tr></table>`],
    ["留意事項通知（サンプル）", 375, `<h2>区分番号「C000」歯科訪問診療料</h2><p>(1) 在宅等において療養を行っている患者であって、通院が困難なものに対して、患家の求めに応じ訪問して歯科診療を行った場合に算定する。</p><p>なお、同一建物居住者に対して行った場合は、人数に応じた区分により算定する。</p>`],
  ],
  "akahon_sample_536-538_short.pdf": null,
  "akahon_sample_failed.pdf": [
    ["歯科診療報酬点数表（サンプル）", 600, `<h2>M019 熱可塑性樹脂有床義歯</h2><p>1 局部義歯 1,250点</p><p>2 総義歯 2,620点</p>`],
    ["歯科診療報酬点数表（サンプル）", 601, `<h2>M020 鋳造鉤</h2><p>1 双子鉤 255点</p><p>2 二腕鉤 240点</p>`],
  ],
};
docs["akahon_sample_536-538_short.pdf"] = docs["akahon_sample_536-543.pdf"].slice(0, 3);

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const [name, pages] of Object.entries(docs)) {
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${pages.map(([t, n, body, logo]) => sec(t, n, body, logo)).join("")}</body></html>`;
    await p.setContent(html);
    await p.pdf({ path: `${out}/${name}`, format: "A4", printBackground: true });
    console.log(`${out}/${name}`);
  }
  await b.close();
})();
