/*
 * math.js -- dependency-free, DOM-free TeX-ish renderer.
 *
 * Browser:  <script src="math.js"></script>  ->  window.MathRender
 * Node:     const MathRender = require('./math.js')
 *
 * The renderer only ever emits generated HTML plus escaped input text.
 * Unknown TeX is degraded to escaped literal text; malformed input never throws.
 */
(function (global) {
  'use strict';

  var HTML_ESCAPES = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;'
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, function (ch) {
      return HTML_ESCAPES[ch];
    });
  }

  var GREEK = {
    alpha: '\u03b1', beta: '\u03b2', gamma: '\u03b3', delta: '\u03b4',
    epsilon: '\u03b5', varepsilon: '\u03f5', zeta: '\u03b6', eta: '\u03b7',
    theta: '\u03b8', vartheta: '\u03d1', iota: '\u03b9', kappa: '\u03ba',
    varkappa: '\u03f0', lambda: '\u03bb', mu: '\u03bc', nu: '\u03bd',
    xi: '\u03be', omicron: '\u03bf', pi: '\u03c0', varpi: '\u03d6',
    rho: '\u03c1', varrho: '\u03f1', sigma: '\u03c3', varsigma: '\u03c2',
    tau: '\u03c4', upsilon: '\u03c5', phi: '\u03c6', varphi: '\u03d5',
    chi: '\u03c7', psi: '\u03c8', omega: '\u03c9',
    Gamma: '\u0393', Delta: '\u0394', Theta: '\u0398', Lambda: '\u039b',
    Xi: '\u039e', Pi: '\u03a0', Sigma: '\u03a3', Upsilon: '\u03a5',
    Phi: '\u03a6', Psi: '\u03a8', Omega: '\u03a9'
  };

  var SYMBOLS = {
    cdot: '\u00b7', times: '\u00d7', div: '\u00f7', pm: '\u00b1', mp: '\u2213',
    le: '\u2264', leq: '\u2264', ge: '\u2265', geq: '\u2265',
    ne: '\u2260', neq: '\u2260', approx: '\u2248', equiv: '\u2261',
    sim: '\u223c', simeq: '\u2243', cong: '\u2245', propto: '\u221d',
    infty: '\u221e', partial: '\u2202', nabla: '\u2207',
    sum: '\u2211', prod: '\u220f', int: '\u222b', iint: '\u222c',
    iiint: '\u222d', oint: '\u222e',
    to: '\u2192', rightarrow: '\u2192', leftarrow: '\u2190',
    leftrightarrow: '\u2194', Rightarrow: '\u21d2', Leftarrow: '\u21d0',
    Leftrightarrow: '\u21d4', implies: '\u21d2', iff: '\u21d4',
    mapsto: '\u21a6', uparrow: '\u2191', downarrow: '\u2193',
    forall: '\u2200', exists: '\u2203', nexists: '\u2204',
    in: '\u2208', notin: '\u2209', ni: '\u220b',
    subset: '\u2282', subseteq: '\u2286', supset: '\u2283', supseteq: '\u2287',
    cup: '\u222a', cap: '\u2229', setminus: '\u2216', backslash: '\u2216',
    emptyset: '\u2205', varnothing: '\u2205',
    cdots: '\u22ef', ldots: '\u2026', dots: '\u2026', vdots: '\u22ee', ddots: '\u22f1',
    angle: '\u2220', triangle: '\u25b3', square: '\u25a1',
    perp: '\u22a5', parallel: '\u2225', nparallel: '\u2226',
    circ: '\u2218', bullet: '\u2022', star: '\u22c6', ast: '\u2217',
    oplus: '\u2295', otimes: '\u2297',
    therefore: '\u2234', because: '\u2235',
    neg: '\u00ac', lnot: '\u00ac', land: '\u2227', lor: '\u2228',
    mid: '\u2223', nmid: '\u2224',
    langle: '\u27e8', rangle: '\u27e9', lceil: '\u2308', rceil: '\u2309',
    lfloor: '\u230a', rfloor: '\u230b',
    aleph: '\u2135', Re: '\u211c', Im: '\u2111', prime: '\u2032',
    degree: '\u00b0', ell: '\u2113', hbar: '\u210f'
  };
  // 教材里常见、但基础表没覆盖的变体（不带这些会原样漏出 \leqslant 这种字面量）
  var SYMBOLS_EXTRA = {
    leqslant: '\u2a7d', geqslant: '\u2a7e',
    nleqslant: '\u2a7d\u0338', ngeqslant: '\u2a7e\u0338',
    lneq: '\u2a87', gneq: '\u2a88', lneqq: '\u2268', gneqq: '\u2269',
    nleq: '\u2270', ngeq: '\u2271', nless: '\u226e', ngtr: '\u226f',
    nsubset: '\u2284', nsupset: '\u2285',
    subsetneq: '\u228a', supsetneq: '\u228b',
    nsubseteq: '\u2288', nsupseteq: '\u2289',
    lesssim: '\u2272', gtrsim: '\u2273', lessgtr: '\u2276', gtrless: '\u2277',
    ll: '\u226a', gg: '\u226b', prec: '\u2aaf', succ: '\u2ab0',
    preceq: '\u2aaf', succeq: '\u2ab0',
    asymp: '\u224d', doteq: '\u2250', triangleq: '\u225c',
    nequiv: '\u2262', ncong: '\u2247', nsim: '\u2241', napprox: '\u2249',
    vdash: '\u22a2', dashv: '\u22a3', models: '\u22a8',
    top: '\u22a4', bot: '\u22a5', complement: '\u2201',
    dagger: '\u2020', ddagger: '\u2021', checkmark: '\u2713',
    lozenge: '\u25ca', blacksquare: '\u25a0', bigcirc: '\u25ef',
    hbar: '\u210f', ell: '\u2113', aleph: '\u2135', wp: '\u2118',
    Re: '\u211c', Im: '\u2111', mho: '\u2127', degree: '\u00b0',
    prime: '\u2032', backprime: '\u2035', section: '\u00a7',
    coloneq: '\u2254', eqcolon: '\u2255',
  };
  for (var _k in SYMBOLS_EXTRA) {
    if (SYMBOLS[_k] === undefined) SYMBOLS[_k] = SYMBOLS_EXTRA[_k];
  }


  var FUNCTIONS = {
    sin: true, cos: true, tan: true, cot: true, sec: true, csc: true,
    arcsin: true, arccos: true, arctan: true,
    sinh: true, cosh: true, tanh: true,
    log: true, ln: true, lg: true, exp: true,
    max: true, min: true, sup: true, inf: true,
    limsup: true, liminf: true, det: true, dim: true, ker: true,
    deg: true
  };

  var LARGE_OPERATORS = {
    sum: { symbol: '\u2211', className: 'math-sum', size: '1.32em' },
    prod: { symbol: '\u220f', className: 'math-prod', size: '1.32em' },
    int: { symbol: '\u222b', className: 'math-int', size: '1.38em' },
    iint: { symbol: '\u222c', className: 'math-iint', size: '1.38em' },
    iiint: { symbol: '\u222d', className: 'math-iiint', size: '1.38em' },
    oint: { symbol: '\u222e', className: 'math-oint', size: '1.38em' }
  };

  var BLACKBOARD = {
    R: '\u211d', N: '\u2115', Z: '\u2124', Q: '\u211a', C: '\u2102',
    P: '\u2119', H: '\u210d'
  };

  var ACCENTS = {
    vec: { mark: '\u2192', className: 'math-vec' },
    hat: { mark: '^', className: 'math-hat' },
    widehat: { mark: '^', className: 'math-hat' },
    dot: { mark: '\u00b7', className: 'math-dot' },
    bar: { mark: '\u203e', className: 'math-bar' }
  };

  function isLetter(ch) {
    return ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z';
  }

  function isSpace(ch) {
    return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r';
  }

  function isEscapedAt(text, pos) {
    var count = 0;
    for (var i = pos - 1; i >= 0 && text.charAt(i) === '\\'; i--) {
      count++;
    }
    return count % 2 === 1;
  }

  function findDollarClose(text, from, delimiter) {
    var i = from;
    while (i < text.length) {
      if (text.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      if (text.startsWith(delimiter, i)) {
        return i;
      }
      i++;
    }
    return -1;
  }

  function isCommandAt(text, pos, name) {
    if (!text.startsWith('\\' + name, pos)) {
      return false;
    }
    var after = text.charAt(pos + 1 + name.length);
    return after === '' || !isLetter(after);
  }

  function findMatchingRight(text, from) {
    var depth = 1;
    var i = from;
    while (i < text.length) {
      if (text.charAt(i) === '\\') {
        if (isCommandAt(text, i, 'left')) {
          depth++;
          i += 5;
          continue;
        }
        if (isCommandAt(text, i, 'right')) {
          depth--;
          if (depth === 0) {
            return i;
          }
          i += 6;
          continue;
        }
        i += 2;
        continue;
      }
      i++;
    }
    return -1;
  }

  function findEnvironmentEnd(text, from, envName) {
    var depth = 1;
    var i = from;
    while (i < text.length) {
      if (text.charAt(i) !== '\\') {
        i++;
        continue;
      }
      var token = null;
      var isBegin = isCommandAt(text, i, 'begin');
      var isEnd = isCommandAt(text, i, 'end');
      if (isBegin || isEnd) {
        var j = i + (isBegin ? 6 : 4);
        while (j < text.length && isSpace(text.charAt(j))) {
          j++;
        }
        if (text.charAt(j) === '{') {
          var close = text.indexOf('}', j + 1);
          if (close !== -1) {
            token = text.slice(j + 1, close).trim();
            if (token === envName) {
              if (isBegin) {
                depth++;
              } else {
                depth--;
                if (depth === 0) {
                  return { bodyEnd: i, end: close + 1 };
                }
              }
            }
            i = close + 1;
            continue;
          }
        }
      }
      i += 2;
    }
    return null;
  }

  function splitEnvironmentRows(body, keepEmptyRows) {
    var rows = [];
    var cells = [];
    var current = '';
    var depth = 0;
    var i = 0;
    while (i < body.length) {
      var ch = body.charAt(i);
      if (ch === '\\') {
        if (body.charAt(i + 1) === '\\' && depth === 0) {
          cells.push(current);
          rows.push(cells);
          cells = [];
          current = '';
          i += 2;
          continue;
        }
        current += ch;
        if (i + 1 < body.length) {
          current += body.charAt(i + 1);
          i += 2;
        } else {
          i++;
        }
        continue;
      }
      if (ch === '{') {
        depth++;
      } else if (ch === '}' && depth > 0) {
        depth--;
      }
      if (ch === '&' && depth === 0) {
        cells.push(current);
        current = '';
        i++;
        continue;
      }
      current += ch;
      i++;
    }
    cells.push(current);
    rows.push(cells);
    if (!keepEmptyRows) {
      while (rows.length > 0) {
        var last = rows[rows.length - 1];
        var allEmpty = true;
        for (var k = 0; k < last.length; k++) {
          if (last[k].trim() !== '') {
            allEmpty = false;
            break;
          }
        }
        if (allEmpty) {
          rows.pop();
        } else {
          break;
        }
      }
    }
    return rows;
  }

  function renderRows(rows, display) {
    var html = [];
    for (var r = 0; r < rows.length; r++) {
      var cells = rows[r];
      var cellHtml = [];
      for (var c = 0; c < cells.length; c++) {
        var parsed = new TexParser(cells[c], display).parse();
        var align = c % 2 === 0 ? 'right' : 'left';
        cellHtml.push(
          '<span class="math-cell" style="text-align:' + align + ';padding:0 .22em">' +
          parsed + '</span>'
        );
      }
      html.push('<span class="math-row" style="display:contents">' + cellHtml.join('') + '</span>');
    }
    return html.join('');
  }

  function limitHtml(content, kind) {
    if (content == null || content === '') {
      return '';
    }
    return '<span class="math-limits math-limits-' + kind +
      '" style="font-size:.72em;line-height:1.05;white-space:nowrap">' +
      content + '</span>';
  }

  function limitLayout(symbolHtml, sup, sub, extraClass) {
    return '<span class="math-op-limits ' + extraClass +
      '" style="display:inline-flex;flex-direction:column;align-items:center;justify-content:center;' +
      'vertical-align:middle;line-height:1.05;margin:0 .16em;text-align:center">' +
      limitHtml(sup, 'upper') + symbolHtml + limitHtml(sub, 'lower') +
      '</span>';
  }

  function fractionHtml(numerator, denominator, size, extraClass, display) {
    var classes = 'math-frac';
    if (extraClass) {
      classes += ' ' + extraClass;
    }
    if (display) {
      classes += ' math-display-frac';
    }
    return '<span class="' + classes + '" style="display:inline-flex;flex-direction:column;align-items:center;justify-content:center;' +
      'vertical-align:middle;text-align:center;margin:0 .14em;line-height:1.12;font-size:' + size + '">' +
      '<span class="math-frac-num" style="display:block;padding:0 .18em;line-height:1.12;white-space:nowrap">' +
      numerator + '</span>' +
      '<span class="math-frac-den" style="display:block;padding:0 .18em;line-height:1.12;' +
      'border-top:1px solid currentColor;white-space:nowrap">' + denominator + '</span>' +
      '</span>';
  }

  function accentHtml(base, mark, className) {
    return '<span class="math-accent ' + className +
      '" style="display:inline-flex;flex-direction:column;align-items:center;justify-content:center;' +
      'vertical-align:middle;line-height:1">' +
      '<span class="math-accent-mark" style="font-size:.68em;line-height:1">' + mark + '</span>' +
      '<span class="math-accent-base" style="line-height:1.12">' + base + '</span>' +
      '</span>';
  }

  function TexParser(source, display) {
    this.src = String(source == null ? '' : source);
    this.i = 0;
    this.display = !!display;
  }

  TexParser.prototype.parse = function () {
    return this.parseSequence('').html;
  };

  TexParser.prototype.parseSequence = function (stop) {
    var parts = [];
    var closed = false;
    while (this.i < this.src.length) {
      var ch = this.src.charAt(this.i);
      if (stop && ch === stop) {
        this.i++;
        closed = true;
        break;
      }
      if (ch === '}') {
        this.i++;
        parts.push('}');
        continue;
      }
      if (ch === '{') {
        this.i++;
        var group = this.parseSequence('}');
        parts.push(this.attachScripts(group.html));
        continue;
      }
      if (ch === '\\') {
        parts.push(this.attachScripts(this.parseCommand()));
        continue;
      }
      if (ch === '^' || ch === '_') {
        parts.push(this.attachScripts(''));
        continue;
      }
      parts.push(this.attachScripts(this.parseTextToken()));
    }
    return { html: parts.join(''), closed: closed };
  };

  TexParser.prototype.skipSpaces = function () {
    while (this.i < this.src.length && isSpace(this.src.charAt(this.i))) {
      this.i++;
    }
  };

  TexParser.prototype.renderSingleChar = function (ch) {
    if (ch === '&') {
      return '&amp;';
    }
    if (ch === '<' || ch === '>' || ch === '"') {
      return escapeHtml(ch);
    }
    return escapeHtml(ch);
  };

  TexParser.prototype.parseTextToken = function () {
    var ch = this.src.charAt(this.i);
    if (isSpace(ch)) {
      while (this.i < this.src.length && isSpace(this.src.charAt(this.i))) {
        this.i++;
      }
      return ' ';
    }
    if (isLetter(ch)) {
      var start = this.i;
      while (this.i < this.src.length && isLetter(this.src.charAt(this.i))) {
        this.i++;
      }
      var word = this.src.slice(start, this.i);
      if (word.length === 1) {
        return escapeHtml(word);
      }
      return '<span class="math-roman" style="font-style:normal">' + escapeHtml(word) + '</span>';
    }
    if (ch >= '0' && ch <= '9') {
      var numberStart = this.i;
      while (this.i < this.src.length && /[0-9.]/.test(this.src.charAt(this.i))) {
        this.i++;
      }
      return escapeHtml(this.src.slice(numberStart, this.i));
    }
    this.i++;
    return this.renderSingleChar(ch);
  };

  TexParser.prototype.parseArgument = function () {
    this.skipSpaces();
    if (this.i >= this.src.length) {
      return '';
    }
    var ch = this.src.charAt(this.i);
    if (ch === '{') {
      this.i++;
      return this.parseSequence('}').html;
    }
    if (ch === '\\') {
      return this.parseCommand();
    }
    this.i++;
    if (isLetter(ch)) {
      return escapeHtml(ch);
    }
    if (ch >= '0' && ch <= '9') {
      return escapeHtml(ch);
    }
    return this.renderSingleChar(ch);
  };

  TexParser.prototype.attachScripts = function (base) {
    var sup = null;
    var sub = null;
    var consumed = false;
    while (this.i < this.src.length) {
      var j = this.i;
      while (j < this.src.length && isSpace(this.src.charAt(j))) {
        j++;
      }
      var marker = this.src.charAt(j);
      if (marker !== '^' && marker !== '_') {
        break;
      }
      this.i = j + 1;
      var arg = this.parseArgument();
      consumed = true;
      if (marker === '^') {
        sup = sup === null ? arg : sup + arg;
      } else {
        sub = sub === null ? arg : sub + arg;
      }
    }
    if (!consumed) {
      return base;
    }
    var html = '<span class="math-scripted">' + base;
    if (sub !== null) {
      html += '<sub class="math-sub" style="font-size:.75em;line-height:0">' + sub + '</sub>';
    }
    if (sup !== null) {
      html += '<sup class="math-sup" style="font-size:.75em;line-height:0">' + sup + '</sup>';
    }
    return html + '</span>';
  };

  TexParser.prototype.readRawGroup = function () {
    var j = this.i;
    while (j < this.src.length && isSpace(this.src.charAt(j))) {
      j++;
    }
    if (this.src.charAt(j) !== '{') {
      return null;
    }
    var start = j + 1;
    var depth = 0;
    for (; j < this.src.length; j++) {
      var ch = this.src.charAt(j);
      if (ch === '\\') {
        j++;
        continue;
      }
      if (ch === '{') {
        depth++;
      } else if (ch === '}') {
        depth--;
        if (depth === 0) {
          this.i = j + 1;
          return this.src.slice(start, j);
        }
      }
    }
    this.i = this.src.length;
    return this.src.slice(start);
  };

  TexParser.prototype.readOptionalBracket = function () {
    var j = this.i;
    while (j < this.src.length && isSpace(this.src.charAt(j))) {
      j++;
    }
    if (this.src.charAt(j) !== '[') {
      return null;
    }
    var start = j + 1;
    var depth = 0;
    for (j = start; j < this.src.length; j++) {
      var ch = this.src.charAt(j);
      if (ch === '\\') {
        j++;
        continue;
      }
      if (ch === '{') {
        depth++;
      } else if (ch === '}' && depth > 0) {
        depth--;
      } else if (ch === ']' && depth === 0) {
        this.i = j + 1;
        return this.src.slice(start, j);
      }
    }
    return null;
  };

  TexParser.prototype.readDelimiter = function () {
    this.skipSpaces();
    if (this.i >= this.src.length) {
      return '';
    }
    var ch = this.src.charAt(this.i);
    if (ch === '\\') {
      this.i++;
      if (this.i >= this.src.length) {
        return '';
      }
      var next = this.src.charAt(this.i);
      if (isLetter(next)) {
        var start = this.i;
        while (this.i < this.src.length && isLetter(this.src.charAt(this.i))) {
          this.i++;
        }
        var name = this.src.slice(start, this.i);
        var map = {
          lbrace: '{', rbrace: '}', langle: '\u27e8', rangle: '\u27e9',
          lceil: '\u2308', rceil: '\u2309', lfloor: '\u230a', rfloor: '\u230b',
          vert: '|', Vert: '\u2016', lvert: '|', rvert: '|', mid: '|',
          lVert: '\u2016', rVert: '\u2016', lVert: '\u2016',
          uparrow: '\u2191', downarrow: '\u2193', updownarrow: '\u2195',
          Uparrow: '\u21d1', Downarrow: '\u21d3', Updownarrow: '\u21d5',
          backslash: '\\'
        };
        return map[name] !== undefined ? map[name] : '\\' + name;
      }
      this.i++;
      if (next === '|') {
        return '\u2016';
      }
      if (next === '{' || next === '}' || next === '[' || next === ']' ||
          next === '(' || next === ')') {
        return next;
      }
      return '\\' + next;
    }
    this.i++;
    if (ch === '.') {
      return '';
    }
    return ch;
  };

  TexParser.prototype.parseCommand = function () {
    this.i++; // backslash
    if (this.i >= this.src.length) {
      return '\\';
    }
    var ch = this.src.charAt(this.i);

    if (!isLetter(ch)) {
      this.i++;
      return this.commandSymbol(ch);
    }

    var start = this.i;
    while (this.i < this.src.length && isLetter(this.src.charAt(this.i))) {
      this.i++;
    }
    var name = this.src.slice(start, this.i);

    // \big \Big \bigg \Bigg (+ l/r/m variants) size the next delimiter.
    var sized = /^(big|Big|bigg|Bigg)([lrm])?$/.exec(name);
    if (sized) {
      var delimSizes = { big: 1.2, Big: 1.42, bigg: 1.66, Bigg: 1.9 };
      var delim = this.readDelimiter();
      if (delim === '') {
        return '';
      }
      return '<span class="math-delim math-delim-' + sized[1].toLowerCase() +
        '" style="font-size:' + delimSizes[sized[1]] +
        'em;line-height:1;vertical-align:-.14em">' + escapeHtml(delim) + '</span>';
    }

    if (name === 'frac' || name === 'dfrac' || name === 'tfrac') {
      var numerator = this.parseArgument();
      var denominator = this.parseArgument();
      var size;
      if (this.display) {
        size = '1em';
      } else if (name === 'dfrac') {
        size = '1.02em';
      } else if (name === 'tfrac') {
        size = '.75em';
      } else {
        size = '.9em';
      }
      return fractionHtml(numerator, denominator, size,
        name === 'frac' ? '' : 'math-' + name, this.display);
    }

    if (name === 'sqrt') {
      var index = this.readOptionalBracket();
      var indexHtml = '';
      if (index !== null) {
        indexHtml = '<span class="math-sqrt-index" style="font-size:.62em;line-height:1;' +
          'align-self:flex-start;margin-right:.04em">' +
          new TexParser(index, this.display).parse() + '</span>';
      }
      var radicand = this.parseArgument();
      return '<span class="math-sqrt" style="display:inline-flex;align-items:flex-start;' +
        'vertical-align:middle;line-height:1">' + indexHtml +
        '<span class="math-sqrt-symbol" style="font-size:1.16em;line-height:1;margin-top:.02em">\u221a</span>' +
        '<span class="math-sqrt-radicand" style="padding:0 .12em;border-top:1px solid currentColor;' +
        'line-height:1.15">' + radicand + '</span></span>';
    }

    if (name === 'left') {
      return this.parseLeftRight();
    }

    if (name === 'right') {
      // Reaching a \right without a matching \left is malformed; keep it visible.
      return escapeHtml('\\right');
    }

    if (name === 'begin') {
      return this.parseEnvironment();
    }

    if (name === 'text') {
      var text = this.readRawGroup();
      if (text === null) {
        return escapeHtml('\\text');
      }
      return '<span class="math-text" style="white-space:pre;font-style:normal">' +
        escapeHtml(text) + '</span>';
    }

    if (name === 'mathrm') {
      return '<span class="math-roman" style="font-style:normal">' +
        this.parseArgument() + '</span>';
    }

    if (name === 'mathbf') {
      return '<span class="math-bold" style="font-weight:700">' +
        this.parseArgument() + '</span>';
    }

    if (name === 'mathbb') {
      var bbRaw = this.readRawGroup();
      if (bbRaw === null) {
        return escapeHtml('\\mathbb');
      }
      var mapped = '';
      for (var b = 0; b < bbRaw.length; b++) {
        var sourceChar = bbRaw.charAt(b);
        mapped += BLACKBOARD[sourceChar] || sourceChar;
      }
      return '<span class="math-bb" style="font-style:normal">' + escapeHtml(mapped) + '</span>';
    }

    if (name === 'overline') {
      return '<span class="math-overline" style="text-decoration:overline;' +
        'text-decoration-thickness:1px;padding:0 .04em">' + this.parseArgument() + '</span>';
    }

    if (ACCENTS[name]) {
      return accentHtml(this.parseArgument(), ACCENTS[name].mark, ACCENTS[name].className);
    }

    if (name === 'operatorname') {
      if (this.src.charAt(this.i) === '*') {
        this.i++;
      }
      var opName = this.readRawGroup();
      if (opName === null) {
        return escapeHtml('\\operatorname');
      }
      return '<span class="math-fn math-roman" style="font-style:normal">' +
        escapeHtml(opName.trim()) + '</span>';
    }

    if (name === 'lim') {
      return this.parseLimitOperator('lim', true);
    }

    if (name === 'limsup' || name === 'liminf') {
      return this.parseLimitOperator(name, true);
    }

    if (LARGE_OPERATORS[name]) {
      return this.parseLargeOperator(name);
    }

    if (name === 'quad' || name === 'qquad') {
      return '<span class="math-space math-space-' + name + '">' +
        (name === 'qquad' ? '\u2003\u2003' : '\u2003') + '</span>';
    }

    // ---- 常见命令的兜底：不认识就原样漏出 \\xxx，看起来像“崩了” ----
    var WRAP_COMMANDS = {
      text: 1, textrm: 1, textsf: 1, texttt: 1, textbf: 1, textit: 1,
      mathrm: 1, mathbf: 1, mathit: 1, mathsf: 1, mathtt: 1, mathbb: 1,
      mathcal: 1, mathfrak: 1, boldsymbol: 1, operatorname: 1,
      overline: 1, underline: 1, hat: 1, widehat: 1, bar: 1, vec: 1,
      tilde: 1, widetilde: 1, dot: 1, ddot: 1, overrightarrow: 1,
      overleftarrow: 1, underbrace: 1, overbrace: 1,
    };
    if (WRAP_COMMANDS[name]) {
      var wrapped = this.parseArgument();
      if (name === 'boxed') {
        return '<span class="math-boxed" style="border:1px solid currentColor;' +
          'padding:0 .25em;border-radius:3px">' + wrapped + '</span>';
      }
      if (name === 'overline' || name === 'bar') {
        return '<span style="text-decoration:overline">' + wrapped + '</span>';
      }
      if (name === 'underline') {
        return '<span style="text-decoration:underline">' + wrapped + '</span>';
      }
      if (name === 'vec' || name === 'overrightarrow') {
        return '<span style="position:relative">' + wrapped +
          '<span style="position:absolute;left:0;right:0;top:-0.55em;text-align:center">→</span></span>';
      }
      return wrapped;
    }

    if (name === 'boxed') {
      return '<span class="math-boxed" style="border:1px solid currentColor;' +
        'padding:0 .25em;border-radius:3px">' + this.parseArgument() + '</span>';
    }

    var NOOP_COMMANDS = {
      displaystyle: 1, textstyle: 1, scriptstyle: 1, scriptscriptstyle: 1,
      limits: 1, nolimits: 1, nonumber: 1, notag: 1, hfill: 1, strut: 1,
      qquad: 0, quad: 0,
    };
    if (NOOP_COMMANDS[name]) {
      return '';
    }

    var DROP_ARG_COMMANDS = {
      label: 1, color: 1, phantom: 1, vphantom: 1, hphantom: 1,
      hspace: 1, vspace: 1, mspace: 1, kern: 1, clap: 1, mathstrut: 1,
    };
    if (DROP_ARG_COMMANDS[name]) {
      this.parseArgument();
      return '';
    }

    if (name === 'tag') {
      var tagText = this.parseArgument();
      return '<span class="math-tag" style="margin-left:.6em">(' + tagText + ')</span>';
    }

    if (name === 'pmod') {
      return ' <span class="math-fn" style="font-style:normal">(mod ' +
        this.parseArgument() + ')</span>';
    }
    if (name === 'bmod' || name === 'mod') {
      return ' <span class="math-fn" style="font-style:normal">mod</span> ';
    }
    if (name === 'binom') {
      var top = this.parseArgument();
      var bottom = this.parseArgument();
      return 'C(' + top + '\u2009,\u2009' + bottom + ')';
    }
    if (name === 'substack') {
      return this.parseArgument();
    }
    if (name === 'overset' || name === 'underset') {
      this.parseArgument();
      return this.parseArgument();
    }
    if (name === 'lVert' || name === 'rVert' || name === 'Vert') {
      return '\u2016';
    }
    if (name === 'lvert' || name === 'rvert' || name === 'vert') {
      return '|';
    }
    if (name === 'qed') {
      return '\u220e';
    }

    if (GREEK[name] !== undefined) {
      return GREEK[name];
    }
    if (SYMBOLS[name] !== undefined) {
      return SYMBOLS[name];
    }
    if (name === 'not') {
      return '\u2260';
    }
    if (FUNCTIONS[name]) {
      return '<span class="math-fn math-roman" style="font-style:normal">' +
        escapeHtml(name) + '</span>';
    }

    return escapeHtml('\\' + name);
  };

  TexParser.prototype.commandSymbol = function (ch) {
    var spacing = {
      ',': '<span class="math-space math-space-thin">\u2009</span>',
      ';': '<span class="math-space math-space-thick">\u2005</span>',
      ':': '<span class="math-space math-space-medium">\u2004</span>',
      '!': '<span class="math-space math-space-negative" style="display:inline-block;' +
        'width:0;margin-left:-.16em"></span>',
      ' ': '<span class="math-space math-space-normal">\u00a0</span>'
    };
    if (spacing[ch] !== undefined) {
      return spacing[ch];
    }
    if (ch === '\\') {
      return '<br>';
    }
    if (ch === '{' || ch === '}' || ch === '$' || ch === '%' || ch === '#' || ch === '_') {
      return escapeHtml(ch);
    }
    if (ch === '&') {
      return '&amp;';
    }
    if (ch === '|') {
      return '\u2016';
    }
    return escapeHtml('\\' + ch);
  };

  TexParser.prototype.parseLeftRight = function () {
    var open = this.readDelimiter();
    var contentStart = this.i;
    var rightPos = findMatchingRight(this.src, contentStart);
    if (rightPos < 0) {
      var rest = this.src.slice(contentStart);
      this.i = this.src.length;
      return escapeHtml(open) + new TexParser(rest, this.display).parse();
    }
    var content = this.src.slice(contentStart, rightPos);
    this.i = rightPos + 6; // "\right"
    var close = this.readDelimiter();
    var inner = new TexParser(content, this.display).parse();
    return escapeHtml(open) + '<span class="math-delimited-body">' + inner +
      '</span>' + escapeHtml(close);
  };

  TexParser.prototype.consumeLimits = function () {
    var sup = null;
    var sub = null;
    for (var n = 0; n < 2; n++) {
      var j = this.i;
      while (j < this.src.length && isSpace(this.src.charAt(j))) {
        j++;
      }
      var marker = this.src.charAt(j);
      if (marker !== '^' && marker !== '_') {
        break;
      }
      if (marker === '^' && sup !== null) {
        break;
      }
      if (marker === '_' && sub !== null) {
        break;
      }
      this.i = j + 1;
      var arg = this.parseArgument();
      if (marker === '^') {
        sup = arg;
      } else {
        sub = arg;
      }
    }
    return { sup: sup, sub: sub };
  };

  TexParser.prototype.parseLargeOperator = function (name) {
    var op = LARGE_OPERATORS[name];
    var limits = this.consumeLimits();
    var symbolHtml = '<span class="math-op-symbol ' + op.className +
      '" style="font-size:' + op.size + ';line-height:1">' + op.symbol + '</span>';
    if (limits.sup === null && limits.sub === null) {
      return '<span class="math-large-operator">' + symbolHtml + '</span>';
    }
    return limitLayout(symbolHtml, limits.sup, limits.sub, 'math-large-operator-limits');
  };

  TexParser.prototype.parseLimitOperator = function (name, upright) {
    var limits = this.consumeLimits();
    var label = escapeHtml(name);
    var symbolHtml = '<span class="math-op-symbol math-fn' +
      (upright ? ' math-roman' : '') + '" style="font-size:1em;line-height:1.1;font-style:normal">' +
      label + '</span>';
    if (limits.sup === null && limits.sub === null) {
      return '<span class="math-fn math-roman">' + label + '</span>';
    }
    return limitLayout(symbolHtml, limits.sup, limits.sub, 'math-limit-operator');
  };

  TexParser.prototype.parseEnvironment = function () {
    var envRaw = this.readRawGroup();
    if (envRaw === null) {
      return escapeHtml('\\begin');
    }
    var envName = envRaw.trim();
    var bodyStart = this.i;
    var end = findEnvironmentEnd(this.src, bodyStart, envName);
    var body;
    if (end) {
      body = this.src.slice(bodyStart, end.bodyEnd);
      this.i = end.end;
    } else {
      body = this.src.slice(bodyStart);
      this.i = this.src.length;
    }

    if (envName === 'cases') {
      return this.renderCases(body);
    }
    if (envName === 'matrix' || envName === 'pmatrix' || envName === 'bmatrix' ||
        envName === 'Bmatrix' || envName === 'vmatrix') {
      return this.renderMatrix(body, envName);
    }
    if (envName === 'aligned' || envName === 'align' || envName === 'align*' ||
        envName === 'gathered') {
      return this.renderAligned(body);
    }

    var raw = '\\begin{' + envName + '}' + body + (end ? '\\end{' + envName + '}' : '');
    return '<span class="math-unknown-env">' + escapeHtml(raw) + '</span>';
  };

  TexParser.prototype.renderCases = function (body) {
    var rows = splitEnvironmentRows(body, false);
    var rowHtml = [];
    for (var r = 0; r < rows.length; r++) {
      var cells = rows[r];
      var cellHtml = [];
      for (var c = 0; c < cells.length; c++) {
        var content = new TexParser(cells[c], this.display).parse();
        cellHtml.push('<span class="math-cell" style="padding:0 .35em 0 0;text-align:left">' +
          content + '</span>');
      }
      rowHtml.push('<span class="math-row" style="display:contents">' + cellHtml.join('') + '</span>');
    }
    var brace = '<span class="math-cases-brace" style="font-size:' +
      Math.max(1.7, rows.length * 1.15) + 'em;line-height:1;font-weight:400;' +
      'align-self:stretch;display:flex;align-items:center">{</span>';
    return '<span class="math-cases" style="display:inline-flex;align-items:stretch;' +
      'justify-content:flex-start;vertical-align:middle">' + brace +
      '<span class="math-cases-body" style="display:inline-grid;grid-auto-flow:row;' +
      'grid-template-columns:auto auto;column-gap:.55em;row-gap:.24em;align-items:center;' +
      'text-align:left">' + rowHtml.join('') + '</span></span>';
  };

  TexParser.prototype.renderMatrix = function (body, envName) {
    var rows = splitEnvironmentRows(body, false);
    var rowHtml = [];
    for (var r = 0; r < rows.length; r++) {
      var cells = rows[r];
      var cellHtml = [];
      for (var c = 0; c < cells.length; c++) {
        var content = new TexParser(cells[c], true).parse();
        cellHtml.push('<span class="math-cell" style="padding:.1em .45em;text-align:center">' +
          content + '</span>');
      }
      rowHtml.push('<span class="math-row" style="display:contents">' + cellHtml.join('') + '</span>');
    }
    var open = '';
    var close = '';
    if (envName === 'pmatrix') {
      open = '(';
      close = ')';
    } else if (envName === 'bmatrix') {
      open = '[';
      close = ']';
    } else if (envName === 'Bmatrix') {
      open = '{';
      close = '}';
    } else if (envName === 'vmatrix') {
      open = '|';
      close = '|';
    }
    var delimStyle = 'font-size:1.5em;line-height:1;align-self:center;padding:0 .12em';
    return '<span class="math-matrix math-' + envName + '" style="display:inline-flex;' +
      'align-items:center;vertical-align:middle">' +
      (open ? '<span class="math-matrix-delim" style="' + delimStyle + '">' +
        escapeHtml(open) + '</span>' : '') +
      '<span class="math-matrix-body" style="display:inline-grid;grid-auto-flow:row;' +
      'align-items:center;text-align:center">' + rowHtml.join('') + '</span>' +
      (close ? '<span class="math-matrix-delim" style="' + delimStyle + '">' +
        escapeHtml(close) + '</span>' : '') +
      '</span>';
  };

  TexParser.prototype.renderAligned = function (body) {
    var rows = splitEnvironmentRows(body, false);
    var rowHtml = [];
    var maxCells = 2;
    for (var r = 0; r < rows.length; r++) {
      maxCells = Math.max(maxCells, rows[r].length);
    }
    for (var i = 0; i < rows.length; i++) {
      var cellHtml = [];
      for (var c = 0; c < rows[i].length; c++) {
        var content = new TexParser(rows[i][c], this.display).parse();
        var align = c % 2 === 0 ? 'right' : 'left';
        cellHtml.push('<span class="math-cell" style="text-align:' + align + ';padding:0 .22em">' +
          content + '</span>');
      }
      rowHtml.push('<span class="math-row" style="display:contents">' + cellHtml.join('') + '</span>');
    }
    return '<span class="math-aligned" style="display:inline-grid;grid-auto-flow:row;' +
      'grid-template-columns:repeat(' + maxCells + ',auto);column-gap:.25em;row-gap:.24em;' +
      'align-items:baseline;vertical-align:middle;text-align:left">' +
      rowHtml.join('') + '</span>';
  };

  var NOT_MAP = {
    '\\in': '\\notin', '\\subset': '\\nsubset', '\\supset': '\\nsupset',
    '\\equiv': '\\nequiv', '\\cong': '\\ncong', '\\sim': '\\nsim',
    '\\approx': '\\napprox', '\\le': '\\nleq', '\\leq': '\\nleq',
    '\\ge': '\\ngeq', '\\geq': '\\ngeq', '\\mid': '\\nmid',
    '\\parallel': '\\nparallel', '\\ni': '\\nsupset',
    '=': '\\neq', '<': '\\nless', '>': '\\ngtr'
  };

  // “\not\in” 这类组合 TeX 里很常见，渲染器不认识 \not 就会漏出字面量
  function normalizeNot(text) {
    return text.replace(/\\not\s*(\\[a-zA-Z]+|=|<|>)/g, function (m, token) {
      return NOT_MAP[token] || '\\neq';
    });
  }

  function tex(source, display) {
    var src = normalizeNot(String(source == null ? '' : source));
    var body;
    try {
      body = new TexParser(src, !!display).parse();
    } catch (err) {
      body = escapeHtml(src);
    }
    if (display) {
      return '<div class="math display">' + body + '</div>';
    }
    return '<span class="math inline">' + body + '</span>';
  }

  function render(text) {
    var src = String(text == null ? '' : text);
    var out = [];
    var i = 0;
    while (i < src.length) {
      var ch = src.charAt(i);
      if (ch === '\\') {
        var next = src.charAt(i + 1);
        if (next === '$') {
          out.push('$');
          i += 2;
          continue;
        }
        if (next === '(') {
          var inlineEnd = src.indexOf('\\)', i + 2);
          if (inlineEnd !== -1) {
            out.push(tex(src.slice(i + 2, inlineEnd), false));
            i = inlineEnd + 2;
            continue;
          }
          out.push('\\(');
          i += 2;
          continue;
        }
        if (next === '[') {
          var displayEnd = src.indexOf('\\]', i + 2);
          if (displayEnd !== -1) {
            out.push(tex(src.slice(i + 2, displayEnd), true));
            i = displayEnd + 2;
            continue;
          }
          out.push('\\[');
          i += 2;
          continue;
        }
        out.push('\\');
        i++;
        continue;
      }
      if (ch === '$') {
        if (src.charAt(i + 1) === '$') {
          var doubleEnd = findDollarClose(src, i + 2, '$$');
          if (doubleEnd !== -1) {
            out.push(tex(src.slice(i + 2, doubleEnd), true));
            i = doubleEnd + 2;
            continue;
          }
          out.push('$$');
          i += 2;
          continue;
        }
        var singleEnd = findDollarClose(src, i + 1, '$');
        if (singleEnd !== -1) {
          out.push(tex(src.slice(i + 1, singleEnd), false));
          i = singleEnd + 1;
          continue;
        }
        out.push('$');
        i++;
        continue;
      }
      var plainStart = i;
      while (i < src.length && src.charAt(i) !== '$' && src.charAt(i) !== '\\') {
        i++;
      }
      out.push(escapeHtml(src.slice(plainStart, i)));
    }
    return out.join('');
  }

  var API = {
    render: render,
    tex: tex,
    renderInline: render
  };

  if (typeof window !== 'undefined' && window) {
    window.MathRender = API;
  }
  if (typeof module !== 'undefined' && module && module.exports) {
    module.exports = API;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
