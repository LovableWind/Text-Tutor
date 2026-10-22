import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const MathRender = require('../math.js');

let assertionCount = 0;
let testCount = 0;
const failures = [];

function ok(value, message) {
  assertionCount++;
  assert.ok(value, message);
}

function equal(actual, expected, message) {
  assertionCount++;
  assert.strictEqual(actual, expected, message);
}

const eq = equal;

function match(actual, pattern, message) {
  assertionCount++;
  assert.match(actual, pattern, message);
}

function notMatch(actual, pattern, message) {
  assertionCount++;
  assert.doesNotMatch(actual, pattern, message);
}

function noThrow(fn, message) {
  assertionCount++;
  assert.doesNotThrow(fn, message);
}

function count(haystack, needle) {
  return haystack.split(needle).length - 1;
}

function check(name, fn) {
  testCount++;
  try {
    fn();
    console.log(`ok ${testCount} - ${name}`);
  } catch (error) {
    failures.push({ name, error });
    console.error(`not ok ${testCount} - ${name}`);
    console.error(error && error.message ? error.message : error);
  }
}

check('API shape and renderInline alias', () => {
  equal(typeof MathRender.render, 'function', 'render is a function');
  equal(typeof MathRender.tex, 'function', 'tex is a function');
  equal(MathRender.renderInline, MathRender.render, 'renderInline aliases render');
});

check('inline and display wrapper classes', () => {
  const inline = MathRender.render('设 $x+1$。');
  match(inline, /<span class="math inline">/, 'inline span');
  notMatch(inline, /class="math display"/, 'no display in inline text');
  const display = MathRender.render('$$x+1$$');
  match(display, /^<div class="math display">/, 'display div');
});

check('tex() honours the display flag', () => {
  match(MathRender.tex(String.raw`\frac{1}{2}`, false), /^<span class="math inline">/, 'inline tex');
  match(MathRender.tex(String.raw`\frac{1}{2}`, true), /^<div class="math display">/, 'display tex');
  match(MathRender.tex(String.raw`\frac{1}{2}`, true), /math-display-frac/, 'display fraction class');
});

check('Greek letters and common symbols', () => {
  const html = MathRender.tex(String.raw`\alpha+\beta\leq\Gamma`);
  ok(html.includes('\u03b1'), 'alpha becomes Unicode alpha');
  ok(html.includes('\u03b2'), 'beta becomes Unicode beta');
  ok(html.includes('\u2264'), 'leq becomes ≤');
  ok(html.includes('\u0393'), 'Gamma becomes Γ');
});

check('fraction, nested fraction, denominator border', () => {
  const html = MathRender.tex(String.raw`\frac{1}{\frac{2}{3}}`);
  eq((html.match(/class="math-frac(?:\s|")/g) || []).length, 2, 'two fractions are nested');
  ok(html.includes('border-top:1px solid currentColor'), 'denominator has border-top');
  match(html, /math-frac-num/, 'numerator class');
  match(html, /math-frac-den/, 'denominator class');
});

check('dfrac and display fractions use larger sizing', () => {
  const inline = MathRender.tex(String.raw`\frac{1}{2}`, false);
  const dfrac = MathRender.tex(String.raw`\dfrac{1}{2}`, false);
  const display = MathRender.tex(String.raw`\frac{1}{2}`, true);
  ok(inline.includes('font-size:.9em'), 'inline fraction base size');
  ok(dfrac.includes('font-size:1.02em'), 'dfrac is larger inline');
  ok(display.includes('font-size:1em'), 'display fraction is full size');
});

check('square root with and without an index', () => {
  const root = MathRender.tex(String.raw`\sqrt{x+1}`);
  ok(root.includes('\u221a'), 'radical symbol');
  match(root, /math-sqrt-radicand/, 'radicand class');
  ok(root.includes('border-top:1px solid currentColor'), 'radical bar');
  const indexed = MathRender.tex(String.raw`\sqrt[3]{x}`);
  match(indexed, /math-sqrt-index/, 'index class');
  ok(indexed.includes('3'), 'index value');
  ok(indexed.includes('\u221a'), 'indexed radical symbol');
});

check('sum with upper and lower limits', () => {
  const html = MathRender.tex(String.raw`\sum_{i=1}^{n} i`);
  ok(html.includes('\u2211'), 'sum symbol');
  match(html, /math-limits-upper/, 'upper limit block');
  match(html, /math-limits-lower/, 'lower limit block');
  ok(html.includes('i=1'), 'lower limit content');
  ok(html.includes('n'), 'upper limit content');
  match(html, /flex-direction:column/, 'limits are a CSS block');
});

check('integral and lim limits', () => {
  const integral = MathRender.tex(String.raw`\int_{a}^{b} f(x)\,dx`);
  ok(integral.includes('\u222b'), 'integral symbol');
  match(integral, /math-limits-upper/, 'integral upper limit');
  match(integral, /math-limits-lower/, 'integral lower limit');
  const lim = MathRender.tex(String.raw`\lim_{x\to 0} f(x)`);
  ok(lim.includes('lim'), 'lim label');
  ok(lim.includes('\u2192'), 'arrow inside limit');
  match(lim, /math-limits-lower/, 'lim lower limit');
});

check('superscripts, subscripts, and script numbers', () => {
  const html = MathRender.tex(String.raw`x^2+y_{n}`);
  match(html, /<sup class="math-sup"/, 'sup tag');
  match(html, /<sub class="math-sub"/, 'sub tag');
  ok(html.includes('font-size:.75em'), 'scripts use .75em');
  const fraction = MathRender.tex(String.raw`x^{\frac{1}{2}}`);
  match(fraction, /<sup class="math-sup"[^>]*>[\s\S]*math-frac/, 'fraction inside a script');
});

check('left/right delimiters including braces', () => {
  const parens = MathRender.tex(String.raw`\left(\frac{1}{2}\right)`);
  ok(parens.includes('('), 'opening paren');
  ok(parens.includes(')'), 'closing paren');
  match(parens, /math-delimited-body/, 'delimited body wrapper');
  const braces = MathRender.tex(String.raw`\left\{x\right\}`);
  ok(braces.includes('{'), 'opening brace');
  ok(braces.includes('}'), 'closing brace');
});

check('text mode keeps Chinese and escapes HTML', () => {
  const plain = MathRender.tex(String.raw`\text{中文/abc}`);
  ok(plain.includes('中文/abc'), 'Chinese and ASCII text');
  match(plain, /math-text/, 'text class');
  const dangerous = MathRender.tex(String.raw`\text{<script>alert("x")</script> & 1}`);
  notMatch(dangerous, /<script>/, 'no raw script tag');
  ok(dangerous.includes('&lt;script&gt;'), 'angle brackets escaped');
  ok(dangerous.includes('&quot;x&quot;'), 'quotes escaped');
  ok(dangerous.includes('&amp;'), 'ampersand escaped');
});

check('cases environment with two columns and row breaks', () => {
  const html = MathRender.tex(String.raw`\begin{cases} x, & x>0 \\ -x, & x\le 0 \end{cases}`);
  match(html, /math-cases/, 'cases wrapper');
  ok(html.includes('{'), 'left brace');
  eq(count(html, 'class="math-row"'), 2, 'two case rows');
  ok(html.includes('x&gt;0'), 'first row content escaped');
  ok(html.includes('\u2264'), 'second row relation');
});

check('matrix, pmatrix, and bmatrix', () => {
  const matrix = MathRender.tex(String.raw`\begin{matrix} a & b \\ c & d \end{matrix}`);
  match(matrix, /math-matrix/, 'plain matrix wrapper');
  eq(count(matrix, 'class="math-cell"'), 4, 'four matrix cells');
  const pmatrix = MathRender.tex(String.raw`\begin{pmatrix} a & b \\ c & d \end{pmatrix}`);
  match(pmatrix, /math-pmatrix/, 'pmatrix class');
  ok(pmatrix.includes('('), 'pmatrix opening paren');
  ok(pmatrix.includes(')'), 'pmatrix closing paren');
  const bmatrix = MathRender.tex(String.raw`\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}`);
  ok(bmatrix.includes('['), 'bmatrix opening bracket');
  ok(bmatrix.includes(']'), 'bmatrix closing bracket');
});

check('aligned environment aligns rows at ampersands', () => {
  const html = MathRender.tex(String.raw`\begin{aligned} x &= 1 \\ y &= 2 \end{aligned}`);
  match(html, /math-aligned/, 'aligned wrapper');
  eq(count(html, 'class="math-row"'), 2, 'two aligned rows');
  eq(count(html, 'class="math-cell"'), 4, 'two cells per row');
  ok(html.includes('x'), 'left cell content');
  ok(html.includes('= 2'), 'right cell content');
});

check('mathbb maps the common number sets', () => {
  const html = MathRender.tex(String.raw`\mathbb{R}\subset\mathbb{N}\subset\mathbb{Z}`);
  ok(html.includes('\u211d'), 'real numbers');
  ok(html.includes('\u2115'), 'natural numbers');
  ok(html.includes('\u2124'), 'integers');
  notMatch(html, /\\mathbb/, 'mathbb command consumed');
});

check('operatorname and function names are upright text', () => {
  const rank = MathRender.tex(String.raw`\operatorname{rank}(A)`);
  ok(rank.includes('rank'), 'rank text');
  notMatch(rank, /\\operatorname/, 'operatorname consumed');
  match(rank, /math-fn/, 'function class');
  const trig = MathRender.tex(String.raw`\sin x+\log y`);
  ok(trig.includes('sin'), 'sin rendered');
  ok(trig.includes('log'), 'log rendered');
});

check('multi-character identifiers are roman/upright', () => {
  const html = MathRender.tex('abc+xy');
  match(html, /<span class="math-roman"[^>]*>abc<\/span>/, 'abc is upright roman');
  ok(html.includes('xy'), 'two-letter identifier present');
});

check('escaped dollar is literal and does not start math', () => {
  const html = MathRender.render(String.raw`价格是 \$5，公式 $x$。`);
  ok(html.includes('$5'), 'escaped dollar stays visible');
  eq(count(html, 'class="math inline"'), 1, 'only the real formula renders');
  ok(html.includes('价格是'), 'Chinese text preserved');
});

check('malformed dollars stay literal', () => {
  const half = MathRender.render('这不是公式 $ 只有一半');
  eq(count(half, 'class="math inline"'), 0, 'single unmatched dollar is literal');
  ok(half.includes('$'), 'unmatched dollar remains visible');
  const unclosedDisplay = MathRender.render('$$unclosed');
  eq(count(unclosedDisplay, 'class="math display"'), 0, 'unclosed display is literal');
  ok(unclosedDisplay.includes('$$unclosed'), 'unclosed display text kept');
});

check('unbalanced braces do not throw or swallow following text', () => {
  let html;
  noThrow(() => {
    html = MathRender.render('A $\\frac{1}{2$ B');
  }, 'unbalanced fraction does not throw');
  ok(html.includes('A'), 'text before formula kept');
  ok(html.includes('B'), 'text after formula kept');
  match(html, /class="math inline"/, 'partial formula still renders');
});

check('unbalanced left/right and unclosed \\( do not throw', () => {
  let left;
  noThrow(() => {
    left = MathRender.render('$\\left( x$ 后');
  }, 'unbalanced left does not throw');
  ok(left.includes('后'), 'text after unbalanced left kept');
  const open = MathRender.render('前 \\( x 后');
  ok(open.includes('前'), 'text before unclosed inline delimiter kept');
  ok(open.includes('后'), 'text after unclosed inline delimiter kept');
  eq(count(open, 'class="math inline"'), 0, 'unclosed delimiter is not math');
});

check('realistic Chinese sentence with three inline formulas', () => {
  const html = MathRender.render('设 $x>0$，则 $x^2+1$ 大于 $0$，所以结论成立。');
  eq(count(html, 'class="math inline"'), 3, 'three inline formulas');
  ok(html.includes('设 '), 'leading Chinese text');
  ok(html.includes('则 '), 'middle Chinese text');
  ok(html.includes('大于 '), 'descriptive Chinese text');
  ok(html.includes('结论成立'), 'trailing Chinese text');
});

check('unknown commands degrade to escaped literal text', () => {
  let html;
  noThrow(() => {
    html = MathRender.tex(String.raw`\unknowncmd{x}`);
  }, 'unknown command does not throw');
  ok(html.includes('\\unknowncmd'), 'unknown command visible');
  ok(html.includes('x'), 'following argument remains visible');
  const unknownEnv = MathRender.tex(String.raw`\begin{nope}x\\y\end{nope}`);
  ok(unknownEnv.includes('\\begin{nope}'), 'unknown environment visible');
  notMatch(unknownEnv, /<table|<script/, 'unknown environment produces no special tags');
});

check('raw HTML in ordinary math is escaped', () => {
  const html = MathRender.tex('<script>alert("x")</script>');
  notMatch(html, /<script>/, 'no raw script element');
  ok(html.includes('&lt;'), 'opening angle bracket escaped');
  ok(html.includes('&gt;'), 'closing angle bracket escaped');
  ok(html.includes('&quot;x&quot;'), 'quotes escaped');
});

check('display delimiters \\[ ... \\] render a display div', () => {
  const html = MathRender.render('前\\[x^2\\]后');
  ok(html.includes('前'), 'before text');
  ok(html.includes('后'), 'after text');
  match(html, /<div class="math display">/, 'display div generated');
});

check('spacing commands consume their commands', () => {
  const html = MathRender.tex('a\\,b\\;c\\:d\\quad e\\qquad f');
  notMatch(html, /\\[,;:]/ , 'spacing commands consumed');
  eq(count(html, 'class="math-space'), 5, 'five spacing wrappers');
  ok(html.includes('a'), 'content before spaces');
});

check('accents produce marked output', () => {
  const vec = MathRender.tex(String.raw`\vec{AB}`);
  match(vec, /math-vec/, 'vec class');
  ok(vec.includes('\u2192'), 'vector arrow mark');
  ok(vec.includes('AB'), 'accents preserve their base');
  const overline = MathRender.tex(String.raw`\overline{AB}`);
  ok(overline.includes('text-decoration:overline'), 'overline decoration');
});

check('radicals, cases, and matrices escape user HTML', () => {
  const cases = MathRender.tex(String.raw`\begin{cases} <img>, & x>0 \end{cases}`);
  notMatch(cases, /<img/, 'case content cannot create an img tag');
  ok(cases.includes('&lt;'), 'case content opening bracket escaped');
  ok(cases.includes('&gt;'), 'case content closing bracket escaped');
  const root = MathRender.tex('<sqrt>');
  notMatch(root, /<sqrt>/, 'angle brackets do not create tags');
});

check('empty/null input is safe and deterministic', () => {
  equal(MathRender.render(null), '', 'null renders empty');
  equal(MathRender.render(''), '', 'empty string renders empty');
  const source = String.raw`再算 $\frac{1}{2}$，最后 $x^2$。`;
  equal(MathRender.render(source), MathRender.render(source), 'rendering is deterministic');
});

check('sized delimiters \\big \\Big \\bigg \\Bigg render and scale', () => {
  const big = MathRender.tex(String.raw`\Big( x \Big)`);
  match(big, /math-delim-big/, '\\Big emits a sized delimiter class');
  match(big, /font-size:1\.42em/, '\\Big uses the Big scale');
  notMatch(big, /\\Big/, 'the command itself never leaks');
  const small = MathRender.tex(String.raw`\bigl[ x \bigr]`);
  match(small, /font-size:1\.2em/, '\\big uses the small scale');
  equal(count(small, 'math-delim-big'), 2, 'both sides are sized');
  const huge = MathRender.tex(String.raw`\Bigg\{ x \Bigg\}`);
  match(huge, /font-size:1\.9em/, '\\Bigg uses the largest scale');
  ok(huge.includes('{') && huge.includes('}'), 'braces survive as text');
});

check('sized delimiters inside fractions and scripts stay balanced', () => {
  const html = MathRender.tex(String.raw`\frac{\Big( a+b \Big)}{2}`);
  match(html, /math-frac/, 'fraction still renders');
  equal(count(html, 'math-delim-big'), 2, 'both delimiters sized');
  const script = MathRender.tex(String.raw`f\Big(x_0\Big)`);
  ok(script.includes('math-delim-big'), 'delimiters inside a call are sized');
  notMatch(script, /\\Big/, 'no literal command text');
});

check('unknown sizing-like command still degrades to literal text', () => {
  const html = MathRender.tex(String.raw`\biggg( x )`);
  match(html, /\\biggg/, 'unknown command stays visible');
  noThrow(() => MathRender.tex(String.raw`\Big`), 'a lone \\Big does not throw');
});

check('math source contains no innerHTML writes', () => {
  const source = readFileSync(new URL('../math.js', import.meta.url), 'utf8');
  notMatch(source, /\.innerHTML\s*=/, 'no innerHTML assignment');
  notMatch(source, /outerHTML\s*=/, 'no outerHTML assignment');
});

if (failures.length > 0) {
  console.error(`\n${failures.length} test(s) failed after ${assertionCount} passing assertions.`);
  for (const failure of failures) {
    console.error(`  - ${failure.name}: ${failure.error && failure.error.message}`);
  }
  process.exitCode = 1;
} else {
  console.log(`\n${assertionCount} assertions passed in ${testCount} tests.`);
}
