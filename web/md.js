/*
 * md.js -- dependency-free, safe Markdown subset for the margin tutor UI.
 *
 * Browser:  <script src="math.js"></script>
 *           <script src="md.js"></script>   ->  window.MDRender
 * Node:     const MDRender = require('./md.js')
 *
 * All source text is escaped. Only explicitly generated tags and the safe
 * HTML produced by MathRender are emitted. No raw HTML and no DOM APIs.
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

  var resolvedMathRenderer = null;

  function getMathRenderer() {
    if (global.MathRender && typeof global.MathRender.render === 'function') {
      return global.MathRender;
    }
    if (resolvedMathRenderer) {
      return resolvedMathRenderer;
    }
    if (typeof require === 'function') {
      try {
        var loaded = require('./math.js');
        if (loaded && typeof loaded.render === 'function') {
          resolvedMathRenderer = loaded;
          return loaded;
        }
      } catch (err) {
        // Running without math.js is allowed; formulas stay literal and safe.
      }
    }
    return null;
  }

  function renderMath(raw) {
    var math = getMathRenderer();
    if (math) {
      try {
        return math.render(raw);
      } catch (err) {
        // A matcher bug must never take down document rendering.
      }
    }
    return '<span class="math fallback">' + escapeHtml(raw) + '</span>';
  }

  function isBlank(line) {
    return /^[ \t]*$/.test(line);
  }

  function leadingWidth(line) {
    var m = /^[ \t]*/.exec(line);
    return (m ? m[0] : '').replace(/\t/g, '    ').length;
  }

  function calloutClass(raw) {
    var text = String(raw == null ? '' : raw).replace(/^[ \t\n]+/, '');
    if (text.charAt(0) === '\u23ed') { // ⏭
      return 'later';
    }
    if (text.charAt(0) === '\u2795') { // ➕
      return 'extra';
    }
    return null;
  }

  function wrapCallout(html, raw) {
    var cls = calloutClass(raw);
    return cls ? '<div class="callout ' + cls + '">' + html + '</div>' : html;
  }

  function findCodeClose(src, from, runLength) {
    var i = from;
    while (i < src.length) {
      if (src.charAt(i) === '\u0060') {
        var start = i;
        while (i < src.length && src.charAt(i) === '\u0060') {
          i++;
        }
        if (i - start === runLength) {
          return start;
        }
        continue;
      }
      i++;
    }
    return -1;
  }

  function findDollarClose(src, from, delimiter) {
    var i = from;
    while (i < src.length) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      if (src.startsWith(delimiter, i)) {
        return i;
      }
      i++;
    }
    return -1;
  }

  function skipCodeSpan(src, i) {
    var run = 0;
    while (src.charAt(i + run) === '\u0060') {
      run++;
    }
    if (run === 0) {
      return -1;
    }
    var close = findCodeClose(src, i + run, run);
    return close < 0 ? -1 : close + run;
  }

  function skipMathToken(src, i) {
    if (src.charAt(i) !== '$') {
      return -1;
    }
    if (src.charAt(i + 1) === '$') {
      var displayClose = findDollarClose(src, i + 2, '$$');
      return displayClose < 0 ? -1 : displayClose + 2;
    }
    var close = findDollarClose(src, i + 1, '$');
    return close < 0 ? -1 : close + 1;
  }

  function findBoldClose(src, from) {
    var i = from;
    while (i < src.length - 1) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      var codeEnd = skipCodeSpan(src, i);
      if (codeEnd > i) {
        i = codeEnd;
        continue;
      }
      var mathEnd = skipMathToken(src, i);
      if (mathEnd > i) {
        i = mathEnd;
        continue;
      }
      if (src.charAt(i) === '*' && src.charAt(i + 1) === '*') {
        return i;
      }
      i++;
    }
    return -1;
  }

  function findItalicClose(src, from) {
    var i = from;
    while (i < src.length) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      var codeEnd = skipCodeSpan(src, i);
      if (codeEnd > i) {
        i = codeEnd;
        continue;
      }
      var mathEnd = skipMathToken(src, i);
      if (mathEnd > i) {
        i = mathEnd;
        continue;
      }
      if (src.charAt(i) === '*') {
        if (src.charAt(i + 1) === '*') {
          var boldEnd = findBoldClose(src, i + 2);
          if (boldEnd >= 0) {
            i = boldEnd + 2;
            continue;
          }
          i += 2;
          continue;
        }
        return i;
      }
      i++;
    }
    return -1;
  }

  function findStrikeClose(src, from) {
    var i = from;
    while (i < src.length - 1) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      var codeEnd = skipCodeSpan(src, i);
      if (codeEnd > i) {
        i = codeEnd;
        continue;
      }
      var mathEnd = skipMathToken(src, i);
      if (mathEnd > i) {
        i = mathEnd;
        continue;
      }
      if (src.charAt(i) === '~' && src.charAt(i + 1) === '~') {
        return i;
      }
      i++;
    }
    return -1;
  }

  function findClosingBracket(src, from) {
    var depth = 1;
    var i = from;
    while (i < src.length) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      if (src.charAt(i) === '[') {
        depth++;
      } else if (src.charAt(i) === ']') {
        depth--;
        if (depth === 0) {
          return i;
        }
      }
      i++;
    }
    return -1;
  }

  function findClosingParen(src, from) {
    var depth = 1;
    var i = from;
    while (i < src.length) {
      if (src.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      if (src.charAt(i) === '(') {
        depth++;
      } else if (src.charAt(i) === ')') {
        depth--;
        if (depth === 0) {
          return i;
        }
      }
      i++;
    }
    return -1;
  }

  function parseLinkAt(src, i) {
    var isImage = false;
    var start = i;
    if (src.charAt(i) === '!') {
      isImage = true;
      start = i + 1;
    }
    if (src.charAt(start) !== '[') {
      return null;
    }
    var labelEnd = findClosingBracket(src, start + 1);
    if (labelEnd < 0 || src.charAt(labelEnd + 1) !== '(') {
      return null;
    }
    var urlEnd = findClosingParen(src, labelEnd + 2);
    if (urlEnd < 0) {
      return null;
    }
    return {
      isImage: isImage,
      label: src.slice(start + 1, labelEnd),
      url: src.slice(labelEnd + 2, urlEnd).trim(),
      end: urlEnd + 1
    };
  }

  function isSafeHttpUrl(url) {
    return /^https?:\/\/\S+$/i.test(url) && !/[\u0000-\u0020\u007f]/.test(url);
  }

  var ESCAPABLE = '\\`*_{}[]()#+-.!$~>|';

  function renderInline(src, depth) {
    var level = depth || 0;
    if (level > 16) {
      return escapeHtml(src);
    }
    var out = [];
    var i = 0;
    var n = src.length;
    while (i < n) {
      var ch = src.charAt(i);

      if (ch === '\\') {
        var next = src.charAt(i + 1);
        if (next && ESCAPABLE.indexOf(next) !== -1) {
          out.push(escapeHtml(next));
          i += 2;
        } else {
          out.push('\\');
          i++;
        }
        continue;
      }

      if (ch === '\u0060') { // backtick
        var run = 1;
        while (src.charAt(i + run) === '\u0060') {
          run++;
        }
        var codeClose = findCodeClose(src, i + run, run);
        if (codeClose < 0) {
          out.push(escapeHtml(src.slice(i, i + run)));
          i += run;
          continue;
        }
        var code = src.slice(i + run, codeClose).replace(/\n/g, ' ');
        out.push('<code>' + escapeHtml(code) + '</code>');
        i = codeClose + run;
        continue;
      }

      if (ch === '$') {
        if (src.charAt(i + 1) === '$') {
          var displayClose = findDollarClose(src, i + 2, '$$');
          if (displayClose >= 0) {
            out.push(renderMath(src.slice(i, displayClose + 2)));
            i = displayClose + 2;
            continue;
          }
          out.push('$$');
          i += 2;
          continue;
        }
        var mathClose = findDollarClose(src, i + 1, '$');
        if (mathClose >= 0) {
          out.push(renderMath(src.slice(i, mathClose + 1)));
          i = mathClose + 1;
          continue;
        }
        out.push('$');
        i++;
        continue;
      }

      if (ch === '*' && src.charAt(i + 1) === '*') {
        var boldEnd = findBoldClose(src, i + 2);
        if (boldEnd > i + 2) {
          out.push('<strong>' + renderInline(src.slice(i + 2, boldEnd), level + 1) + '</strong>');
          i = boldEnd + 2;
          continue;
        }
        out.push('**');
        i += 2;
        continue;
      }

      if (ch === '*') {
        var italicEnd = findItalicClose(src, i + 1);
        if (italicEnd > i + 1) {
          out.push('<em>' + renderInline(src.slice(i + 1, italicEnd), level + 1) + '</em>');
          i = italicEnd + 1;
          continue;
        }
        out.push('*');
        i++;
        continue;
      }

      if (ch === '~' && src.charAt(i + 1) === '~') {
        var strikeEnd = findStrikeClose(src, i + 2);
        if (strikeEnd > i + 2) {
          out.push('<del>' + renderInline(src.slice(i + 2, strikeEnd), level + 1) + '</del>');
          i = strikeEnd + 2;
          continue;
        }
        out.push('~~');
        i += 2;
        continue;
      }

      if ((ch === '!' && src.charAt(i + 1) === '[') || ch === '[') {
        var link = parseLinkAt(src, i);
        if (link) {
          var rawLink = src.slice(i, link.end);
          if (!link.isImage && isSafeHttpUrl(link.url)) {
            out.push('<a href="' + escapeHtml(link.url) +
              '" target="_blank" rel="noopener">' +
              renderInline(link.label, level + 1) + '</a>');
          } else {
            // Images are not part of the safe subset, and non-http(s)
            // destinations remain literal source text.
            out.push(escapeHtml(rawLink));
          }
          i = link.end;
          continue;
        }
      }

      if (ch === '\n') {
        out.push('<br>');
        i++;
        continue;
      }

      out.push(escapeHtml(ch));
      i++;
    }
    return out.join('');
  }

  function hasUnescapedDoubleDollar(line) {
    var i = 0;
    while (i < line.length) {
      if (line.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      var codeEnd = skipCodeSpan(line, i);
      if (codeEnd > i) {
        i = codeEnd;
        continue;
      }
      if (line.startsWith('$$', i)) {
        return true;
      }
      i++;
    }
    return false;
  }

  function splitDisplaySegments(raw) {
    var segments = [];
    var last = 0;
    var i = 0;
    while (i < raw.length) {
      if (raw.charAt(i) === '\\') {
        i += 2;
        continue;
      }
      var codeEnd = skipCodeSpan(raw, i);
      if (codeEnd > i) {
        i = codeEnd;
        continue;
      }
      if (raw.startsWith('$$', i)) {
        var close = findDollarClose(raw, i + 2, '$$');
        if (close >= 0) {
          if (i > last) {
            segments.push({ type: 'text', value: raw.slice(last, i) });
          }
          segments.push({
            type: 'math',
            value: raw.slice(i, close + 2)
          });
          i = close + 2;
          last = i;
          continue;
        }
        i += 2;
        continue;
      }
      i++;
    }
    if (last < raw.length) {
      segments.push({ type: 'text', value: raw.slice(last) });
    }
    return segments;
  }

  function renderParagraphRaw(raw) {
    var segments = splitDisplaySegments(raw);
    var hasDisplay = false;
    for (var s = 0; s < segments.length; s++) {
      if (segments[s].type === 'math') {
        hasDisplay = true;
        break;
      }
    }
    var html;
    if (!hasDisplay) {
      html = '<p>' + renderInline(raw) + '</p>';
    } else {
      var parts = [];
      for (var i = 0; i < segments.length; i++) {
        var segment = segments[i];
        if (segment.type === 'math') {
          parts.push(renderMath(segment.value));
        } else {
          var text = segment.value.trim();
          if (text !== '') {
            parts.push('<p>' + renderInline(text) + '</p>');
          }
        }
      }
      html = parts.join('\n');
    }
    return wrapCallout(html, raw);
  }

  function fenceStart(line) {
    return /^ {0,3}\u0060\u0060\u0060/.test(line);
  }

  function fenceEnd(line) {
    return /^ {0,3}\u0060\u0060\u0060[ \t]*$/.test(line);
  }

  function headingMatch(line) {
    return /^ {0,3}(#{1,3})[ \t]+(.*?)[ \t]*$/.exec(line);
  }

  function hrMatch(line) {
    return /^ {0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$/.test(line);
  }

  function blockquoteMatch(line) {
    return /^ {0,3}>[ \t]?(.*)$/.exec(line);
  }

  function listMatch(line) {
    var m = /^([ \t]*)([-*+]|[0-9]+\.)[ \t]+(.*)$/.exec(line);
    if (!m) {
      return null;
    }
    return {
      indent: m[1].replace(/\t/g, '    ').length,
      marker: m[2],
      ordered: /^[0-9]+\.$/.test(m[2]),
      text: m[3]
    };
  }

  function isBlockStart(line) {
    return fenceStart(line) || !!headingMatch(line) || hrMatch(line) ||
      !!blockquoteMatch(line) || !!listMatch(line);
  }

  function parseFence(lines, start) {
    var i = start + 1;
    var content = [];
    while (i < lines.length && !fenceEnd(lines[i])) {
      content.push(lines[i]);
      i++;
    }
    if (i < lines.length) {
      i++;
    }
    return {
      html: '<pre><code>' + escapeHtml(content.join('\n')) + '</code></pre>',
      next: i
    };
  }

  function parseBlockquote(lines, start) {
    var i = start;
    var inner = [];
    while (i < lines.length) {
      var m = blockquoteMatch(lines[i]);
      if (!m) {
        break;
      }
      inner.push(m[1]);
      i++;
    }
    var html = renderBlocks(inner).join('\n');
    return {
      html: html ? '<blockquote>\n' + html + '\n</blockquote>' : '<blockquote></blockquote>',
      next: i
    };
  }

  function isDisplayOnlyParagraph(raw) {
    var segments = splitDisplaySegments(raw);
    var hasMath = false;
    for (var i = 0; i < segments.length; i++) {
      if (segments[i].type === 'math') {
        hasMath = true;
      } else if (segments[i].value.trim() !== '') {
        return false;
      }
    }
    return hasMath;
  }

  function parseParagraph(lines, start) {
    var first = lines[start];
    var trimmedFirst = first.replace(/^[ \t]+/, '');
    var i = start + 1;

    // A line that opens a display formula but does not close it on the same
    // line owns following non-blank lines, including lines that would normally
    // start another block. If it never closes before a blank line we fall back
    // to an ordinary paragraph so malformed input cannot swallow the document.
    if (trimmedFirst.startsWith('$$') && !hasUnescapedDoubleDollar(trimmedFirst.slice(2))) {
      var j = i;
      var foundClose = false;
      while (j < lines.length && !isBlank(lines[j])) {
        if (hasUnescapedDoubleDollar(lines[j])) {
          foundClose = true;
          j++;
          break;
        }
        j++;
      }
      if (foundClose) {
        var displayRaw = lines.slice(start, j).join('\n').trim();
        return {
          html: renderParagraphRaw(displayRaw),
          next: j,
          displayOnly: isDisplayOnlyParagraph(displayRaw)
        };
      }
    }

    while (i < lines.length && !isBlank(lines[i]) && !isBlockStart(lines[i])) {
      i++;
    }
    var raw = lines.slice(start, i).join('\n').trim();
    return {
      html: renderParagraphRaw(raw),
      next: i,
      displayOnly: isDisplayOnlyParagraph(raw)
    };
  }

  function parseList(lines, start, startOverride) {
    var first = listMatch(lines[start]);
    var baseIndent = first.indent;
    var ordered = first.ordered;
    var firstNumber = ordered ? parseInt(first.marker, 10) : 1;
    var startNumber = ordered && startOverride != null ? startOverride : firstNumber;
    var items = [];
    var i = start;

    while (i < lines.length) {
      if (isBlank(lines[i])) {
        break;
      }
      var item = listMatch(lines[i]);
      if (!item || item.indent !== baseIndent || item.ordered !== ordered) {
        break;
      }

      var text = item.text;
      var extras = [];
      i++;

      while (i < lines.length) {
        if (isBlank(lines[i])) {
          break;
        }
        var nested = listMatch(lines[i]);
        if (nested && nested.indent > baseIndent) {
          var nestedResult = parseList(lines, i);
          extras.push(nestedResult.html);
          i = nestedResult.next;
          continue;
        }
        if (!nested && leadingWidth(lines[i]) > baseIndent) {
          text += '\n' + lines[i].trim();
          i++;
          continue;
        }
        break;
      }

      var content = renderInline(text);
      var cls = calloutClass(text);
      if (cls) {
        content = '<div class="callout ' + cls + '">' + content + '</div>';
      }
      items.push('<li>' + content + extras.join('') + '</li>');
    }

    var tag = ordered ? 'ol' : 'ul';
    var startAttribute = ordered && startNumber !== 1
      ? ' start="' + startNumber + '"'
      : '';
    return {
      html: '<' + tag + startAttribute + '>\n' + items.join('\n') + '\n</' + tag + '>',
      next: i,
      ordered: ordered,
      firstNumber: firstNumber,
      startNumber: startNumber,
      lastNumber: ordered ? startNumber + items.length - 1 : null,
      itemCount: items.length
    };
  }

  function renderBlocks(lines) {
    var blocks = [];
    var i = 0;
    // Set only while the current gap since the last top-level ordered list
    // contains nothing but display math. A real paragraph, heading, quote,
    // code block, rule, or different list type clears it.
    var lastOrdered = null;

    while (i < lines.length) {
      if (isBlank(lines[i])) {
        i++;
        continue;
      }

      if (fenceStart(lines[i])) {
        var fence = parseFence(lines, i);
        blocks.push(fence.html);
        lastOrdered = null;
        i = fence.next;
        continue;
      }

      var heading = headingMatch(lines[i]);
      if (heading) {
        var level = heading[1].length + 2; // # -> h3, ## -> h4, ### -> h5
        blocks.push('<h' + level + '>' + renderInline(heading[2]) + '</h' + level + '>');
        lastOrdered = null;
        i++;
        continue;
      }

      if (hrMatch(lines[i])) {
        blocks.push('<hr>');
        lastOrdered = null;
        i++;
        continue;
      }

      if (blockquoteMatch(lines[i])) {
        var quote = parseBlockquote(lines, i);
        blocks.push(quote.html);
        lastOrdered = null;
        i = quote.next;
        continue;
      }

      if (listMatch(lines[i])) {
        var matchedList = listMatch(lines[i]);
        var startOverride = null;
        if (matchedList.ordered && lastOrdered) {
          startOverride = lastOrdered.lastNumber + 1;
        }
        var list = parseList(lines, i, startOverride);
        blocks.push(list.html);
        lastOrdered = list.ordered ? { lastNumber: list.lastNumber } : null;
        i = list.next;
        continue;
      }

      var paragraph = parseParagraph(lines, i);
      if (paragraph.html) {
        blocks.push(paragraph.html);
      }
      // Display-only gaps between ordered lists keep their numbering context.
      if (!paragraph.displayOnly) {
        lastOrdered = null;
      }
      i = paragraph.next;
    }
    return blocks;
  }

  function render(markdownText) {
    var source = String(markdownText == null ? '' : markdownText);
    source = source.replace(/\r\n?/g, '\n');
    var lines = source.split('\n');
    return renderBlocks(lines).join('\n');
  }

  var API = {
    render: render,
    escape: escapeHtml
  };

  if (typeof window !== 'undefined' && window) {
    window.MDRender = API;
  }
  if (typeof module !== 'undefined' && module && module.exports) {
    module.exports = API;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
