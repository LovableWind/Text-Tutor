import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
require('../math.js');
const MDRender = require('../md.js');

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

check('API shape and escape()', () => {
  equal(typeof MDRender.render, 'function', 'render is a function');
  equal(typeof MDRender.escape, 'function', 'escape is a function');
  equal(
    MDRender.escape('<img src=x onerror="alert(1)"> & 1'),
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; 1',
    'escape handles <, >, quotes and ampersands'
  );
});

check('paragraphs and single-newline breaks', () => {
  const html = MDRender.render('第一行\n第二行\n\n第二段');
  ok(html.includes('<p>第一行<br>第二行</p>'), 'newline becomes br inside one paragraph');
  ok(html.includes('<p>第二段</p>'), 'blank line creates a second paragraph');
  eq(count(html, '<p>'), 2, 'exactly two paragraphs');
});

check('headings map to h3/h4/h5 and reserve h1/h2', () => {
  const html = MDRender.render('# 一级\n## 二级\n### 三级\n#### 四级');
  match(html, /<h3>一级<\/h3>/, '# becomes h3');
  match(html, /<h4>二级<\/h4>/, '## becomes h4');
  match(html, /<h5>三级<\/h5>/, '### becomes h5');
  notMatch(html, /<h1>|<h2>|<h6>/, 'no h1, h2 or h6 tags');
  ok(html.includes('<p>#### 四级</p>'), '#### is ordinary paragraph text');
});

check('bold, italic, inline code, and strike', () => {
  const html = MDRender.render('**粗体**、*斜体*、`code <x>`、~~删除~~');
  match(html, /<strong>粗体<\/strong>/, 'bold');
  match(html, /<em>斜体<\/em>/, 'italic');
  match(html, /<code>code &lt;x&gt;<\/code>/, 'inline code escapes HTML');
  match(html, /<del>删除<\/del>/, 'strikethrough');
});

check('unordered lists', () => {
  const html = MDRender.render('- 苹果\n- 香蕉');
  match(html, /^<ul>/, 'unordered list wrapper');
  match(html, /<li>苹果<\/li>/, 'first item');
  match(html, /<li>香蕉<\/li>/, 'second item');
  eq(count(html, '<li>'), 2, 'two list items');
});

check('ordered lists', () => {
  const html = MDRender.render('1. 第一步\n2. 第二步');
  match(html, /^<ol>/, 'ordered list wrapper');
  eq(count(html, '<li>'), 2, 'two ordered items');
  ok(html.includes('第一步'), 'ordered item content');
});

check('display math between ordered lists keeps numbering', () => {
  const html = MDRender.render(
    '1. 第一项\n2. 第二项\n\n$$x^2$$\n\n1. 第三项\n2. 第四项'
  );
  eq(count(html, '<ol'), 2, 'two ordered list blocks');
  match(html, /<ol start="3">/, 'second list continues at previous last + 1');
  eq(count(html, 'start='), 1, 'only the continuation list needs a start attribute');
  const displayIndex = html.indexOf('<div class="math display">');
  const continuationIndex = html.indexOf('<ol start="3">');
  ok(displayIndex > 0 && continuationIndex > displayIndex,
    'display math sits between the two ordered list blocks');
});

check('parent-style numbering: second ordered list marker 2 after display math', () => {
  const html = MDRender.render(
    '1. **有界**\n\n$$a_{n+1}^2-a_n^2>0$$\n\n2. **求 A**'
  );
  match(html, /<ol start="2">/, 'split list resumes at 2');
  eq(count(html, '<ol'), 2, 'two ordered lists');
  ok(html.indexOf('<div class="math display">') < html.indexOf('<ol start="2">'),
    'display math comes before the continuation list');
  ok(html.includes('math-frac-num') === false, 'no accidental fraction markup');
});

check('several display-math gaps still keep ordered numbering', () => {
  const html = MDRender.render(
    '1. 甲\n2. 乙\n\n$$x$$\n\n$$y$$\n\n1. 丙'
  );
  match(html, /<ol start="3">/, 'numbering survives multiple display-only gaps');
  eq(count(html, 'start='), 1, 'one explicit continuation start');
});

check('a normal paragraph resets ordered numbering', () => {
  const html = MDRender.render('1. 原列表\n\n这里是普通的说明段落。\n\n1. 新列表');
  eq(count(html, '<ol'), 2, 'two ordered lists');
  eq(count(html, 'start='), 0, 'the new list restarts at 1');
  ok(html.includes('<p>这里是普通的说明段落。</p>'), 'the interrupting paragraph is normal prose');
  ok(html.includes('新列表'), 'second list content preserved');
});

check('ordered list starting at 3 emits start="3"', () => {
  const html = MDRender.render('3. 第三\n4. 第四');
  match(html, /^<ol start="3">/, 'first ordered list uses its source start number');
  eq(count(html, '<li>'), 2, 'both items preserved');
  eq(count(html, 'start='), 1, 'exactly one start attribute');
});

check('nested unordered list', () => {
  const html = MDRender.render('- 外层一\n  - 内层 A\n  - 内层 B\n- 外层二');
  eq(count(html, '<ul>'), 2, 'outer and inner lists');
  eq(count(html, '<li>'), 4, 'four list items');
  ok(html.includes('内层 A'), 'nested item A');
  ok(html.includes('内层 B'), 'nested item B');
  ok(html.includes('外层二'), 'outer item after nested list');
});

check('nested ordered list inside unordered list', () => {
  const html = MDRender.render('- 章节\n  1. 子项一\n  2. 子项二');
  eq(count(html, '<ul>'), 1, 'outer ul');
  eq(count(html, '<ol>'), 1, 'inner ol');
  ok(html.includes('子项一'), 'nested ordered content');
});

check('blockquote', () => {
  const html = MDRender.render('> 引用中的 **重点**\n> 第二行');
  match(html, /<blockquote>/, 'blockquote wrapper');
  ok(html.includes('引用中的'), 'quote text');
  match(html, /<strong>重点<\/strong>/, 'inline formatting inside quote');
});

check('fenced code block is inert', () => {
  const html = MDRender.render('```\n$x$ <b>raw</b>\n```');
  match(html, /^<pre><code>/, 'pre/code wrapper');
  ok(html.includes('$x$'), 'math delimiter stays literal inside code');
  ok(html.includes('&lt;b&gt;raw&lt;/b&gt;'), 'HTML in code is escaped');
  notMatch(html, /class="math inline"/, 'no math rendering inside fence');
  notMatch(html, /<b>/, 'no raw b element');
  notMatch(html, /<strong>|<em>/, 'no Markdown formatting inside fence');
});

check('code fence with a language marker is still inert', () => {
  const html = MDRender.render('```js\nconst x = $x$;\n```');
  ok(html.includes('$x$'), 'math in language fence stays literal');
  ok(html.includes('const x ='), 'code content preserved');
  notMatch(html, /class="math inline"/, 'no math span inside code fence');
});

check('horizontal rule', () => {
  const html = MDRender.render('上\n\n---\n\n下');
  ok(html.includes('<hr>'), 'hr generated');
  eq(count(html, '<li>'), 0, '--- is not parsed as a list');
});

check('inline math is delegated to MathRender', () => {
  const html = MDRender.render(String.raw`面积是 $\frac{1}{2}$，不是代码。`);
  match(html, /<span class="math inline">/, 'inline math wrapper');
  ok(html.includes('math-frac'), 'fraction rendered by MathRender');
  ok(html.includes('面积是'), 'surrounding Chinese');
  ok(html.includes('不是代码'), 'trailing Chinese');
});

check('display math is split out of paragraphs', () => {
  const html = MDRender.render('前\n\n$$\\sum_{i=1}^{n} i$$\n\n后');
  match(html, /<div class="math display">/, 'display math wrapper');
  ok(html.includes('math-limits-upper'), 'MathRender content is preserved');
  eq(count(html, '<p>'), 2, 'only the two prose paragraphs use p');
  notMatch(html, /<p>\s*<div class="math display">/, 'display div is not nested in p');
  const around = MDRender.render('前 $$x^2$$ 后');
  notMatch(around, /<p><div class="math display">/, 'no p directly wraps an inline-position display');
  ok(around.includes('<p>前</p>'), 'leading prose gets its own p');
  ok(around.includes('<p>后</p>'), 'trailing prose gets its own p');
  const displayIndex = around.indexOf('<div class="math display">');
  const beforeDisplay = around.slice(0, displayIndex);
  ok(beforeDisplay.lastIndexOf('</p>') > beforeDisplay.lastIndexOf('<p>'),
    'prose paragraph is closed before display math');
});

check('safe http(s) links only', () => {
  const html = MDRender.render('[文档](https://example.com/a?x=1&y=2)');
  match(
    html,
    /<a href="https:\/\/example\.com\/a\?x=1&amp;y=2" target="_blank" rel="noopener">文档<\/a>/,
    'http link is escaped and gets target/rel'
  );
  const http = MDRender.render('[站点](http://example.com)');
  match(http, /href="http:\/\/example\.com"/, 'plain http link works');
  const bad = MDRender.render('[点我](javascript:alert(1))');
  notMatch(bad, /<a /, 'javascript URL does not become a link');
  ok(bad.includes('javascript:alert(1)'), 'unsafe URL remains literal text');
  const ftp = MDRender.render('[文件](ftp://example.com/a)');
  notMatch(ftp, /<a /, 'ftp URL does not become a link');
});

check('raw HTML is escaped (XSS attempts)', () => {
  const html = MDRender.render('<img src=x onerror="alert(1)">');
  notMatch(html, /<img/, 'img tag is not emitted');
  ok(html.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'), 'img source escaped');
  const script = MDRender.render('<script>alert(1)</script>');
  notMatch(script, /<script>/, 'script tag is not emitted');
  ok(script.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'script escaped');
  const inBold = MDRender.render('**<script>alert(1)</script>**');
  notMatch(inBold, /<script>/, 'script inside bold is escaped');
  match(inBold, /<strong>&lt;script&gt;/, 'bold wrapper still generated around escaped text');
});

check('HTML in link labels is escaped', () => {
  const html = MDRender.render('[<b>链接</b>](https://example.com)');
  notMatch(html, /<b>/, 'no raw b in link label');
  ok(html.includes('&lt;b&gt;'), 'label escaped');
  match(html, /target="_blank" rel="noopener"/, 'safe link attributes');
});

check('malicious quote in URL cannot break the attribute', () => {
  const html = MDRender.render('[x](http://example.com" onmouseover="alert(1))');
  // The URL contains whitespace after the quote, so it is not a valid http
  // destination and must stay literal; either way no unquoted attribute injection.
  const hrefCount = count(html, '<a ');
  if (hrefCount > 0) {
    notMatch(html, /onmouseover="alert\(1\)"[^>]*>/, 'no injected event handler attribute');
    ok(html.includes('&quot; onmouseover=&quot;'), 'quotes in href are escaped');
  } else {
    ok(html.includes('&quot; onmouseover=&quot;'), 'literal URL is escaped');
  }
});

check('inline code and math do not interfere', () => {
  const html = MDRender.render('`$x$ <b>raw</b>` 与 $x^2$');
  ok(html.includes('<code>$x$ &lt;b&gt;raw&lt;/b&gt;</code>'), 'code span inert and escaped');
  eq(count(html, 'class="math inline"'), 1, 'only the outside formula renders');
  notMatch(html, /<b>/, 'no raw b tag');
});

check('formatting around inline math', () => {
  const html = MDRender.render('**面积 $x^2$ 增大**');
  match(html, /<strong>面积 <span class="math inline">/, 'strong contains math');
  ok(html.includes('增大</strong>'), 'strong closes after trailing text');
});

check('escaped Markdown punctuation stays literal', () => {
  const html = MDRender.render(String.raw`\*不是斜体\* 与 \`不是代码\``);
  notMatch(html, /<em>|<code>/, 'no generated emphasis or code tags');
  ok(html.includes('*不是斜体*'), 'literal asterisks preserved');
  ok(html.includes('`不是代码`'), 'literal backticks preserved');
});

check('malformed Markdown does not throw and stays literal', () => {
  let html;
  noThrow(() => {
    html = MDRender.render('**未闭合 和 *斜体未闭合 和 [链接](http://example.com');
  }, 'malformed Markdown must not throw');
  ok(html.includes('**未闭合'), 'unclosed strong markers remain');
  ok(html.includes('*斜体未闭合'), 'unclosed emphasis marker remains');
  notMatch(html, /<strong>|<em>|<a /, 'no tags generated for broken syntax');
});

check('callouts for paragraphs', () => {
  const later = MDRender.render('⏭ 这个以后会讲\n第二行');
  match(later, /<div class="callout later">/, 'later callout wrapper');
  ok(later.includes('⏭ 这个以后会讲'), 'later marker and text preserved');
  ok(later.includes('<p>'), 'paragraph content retained inside callout');
  const extra = MDRender.render('➕ 补充一个结论');
  match(extra, /<div class="callout extra">/, 'extra callout wrapper');
  ok(extra.includes('➕ 补充一个结论'), 'extra marker and text preserved');
});

check('callouts for list items', () => {
  const html = MDRender.render('- ⏭ 以后再算\n- 现在先算');
  match(html, /<li><div class="callout later">/, 'callout inside list item');
  ok(html.includes('以后再算'), 'callout item text');
  ok(html.includes('现在先算'), 'normal item text');
  ok(html.indexOf('⏭') > html.indexOf('<li>'), 'marker remains in the item');
});

check('callouts with inline math', () => {
  const html = MDRender.render('⏭ 下一节证明 $x^2\\ge 0$。');
  match(html, /<div class="callout later">/, 'callout on a math paragraph');
  match(html, /<span class="math inline">/, 'inline math inside callout');
  ok(html.includes('下一节证明'), 'callout Chinese text');
});

check('ordered and unordered parsing is not confused by markers', () => {
  const ordered = MDRender.render('1. **重点**\n2. 普通');
  match(ordered, /<ol>/, 'ordered list');
  match(ordered, /<li><strong>重点<\/strong><\/li>/, 'bold inside ordered item');
  const unordered = MDRender.render('* 第一\n* 第二');
  match(unordered, /<ul>/, 'asterisk bullet list');
  eq(count(unordered, '<li>'), 2, 'asterisk list items');
});

check('display math only paragraphs generated no p', () => {
  const html = MDRender.render('$$x^2$$');
  match(html, /^<div class="math display">/, 'only display math');
  eq(count(html, '<p>'), 0, 'no empty paragraph around display math');
});

check('null/empty input and deterministic output', () => {
  equal(MDRender.render(null), '', 'null renders empty');
  equal(MDRender.render(''), '', 'empty input renders empty');
  const source = '## 标题\n\n- 第一 $x$\n- 第二\n\n> 引用';
  equal(MDRender.render(source), MDRender.render(source), 'deterministic rendering');
});

check('source contains no innerHTML writes', () => {
  const source = readFileSync(new URL('../md.js', import.meta.url), 'utf8');
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
