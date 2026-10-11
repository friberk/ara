-- Turns the report's GitHub-friendly HTML figures into LaTeX for the PDF.
--
-- report.md writes each figure as centered <p> blocks: one block per panel
-- (<img> + <br> + <em>panel caption</em>) and a final block holding only
-- <em>Figure N: caption</em>. Pandoc keeps those as raw HTML, which the LaTeX
-- writer drops. This filter emits each panel as an unbreakable minipage and
-- attaches the figure caption to the last panel so it never lands alone on
-- the next page. It also drops the GitHub title lines before "Overview",
-- since the PDF gets its own title block.

local function is_html(el, pattern)
  return el.t == "RawInline" and el.format == "html" and el.text:match(pattern)
end

-- Inline content between <em> and </em>, converted to LaTeX.
local function em_text(inlines)
  local out, inside = pandoc.List(), false
  for _, el in ipairs(inlines) do
    if is_html(el, "^<em>$") then
      inside = true
    elseif is_html(el, "^</em>$") then
      inside = false
    elseif inside then
      out:insert(el)
    end
  end
  return pandoc.write(pandoc.Pandoc({ pandoc.Plain(out) }), "latex"):gsub("%s+$", "")
end

local function panel_latex(src, caption, figure_caption)
  local tex = "\\par\\noindent\\begin{minipage}{\\linewidth}\\centering\n"
    .. "\\includegraphics[width=\\linewidth,height=0.42\\textheight,keepaspectratio]{" .. src .. "}\\\\[3pt]\n"
    .. "{\\small\\itshape " .. caption .. "}"
  if figure_caption then
    tex = tex .. "\\\\[6pt]\n{\\small\\sffamily\\color{ece}" .. figure_caption .. "}"
  end
  return tex .. "\n\\end{minipage}\\par\\medskip\n"
end

function Pandoc(doc)
  local blocks, out, panels = doc.blocks, pandoc.List(), {}
  local started = false

  for _, b in ipairs(blocks) do
    if not started then
      if b.t == "Header" and pandoc.utils.stringify(b) == "Overview" then
        started = true
      else
        goto continue
      end
    end

    if b.t == "RawBlock" and b.format == "html" then
      goto continue -- <p align="center">, </p> and <!-- comments -->
    end

    if b.t == "Plain" and #b.content > 0 then
      local first = b.content[1]
      local src = is_html(first, '^<img') and first.text:match('src="([^"]+)"')
      if src then
        table.insert(panels, { src = src, caption = em_text(b.content) })
        goto continue
      end
      if is_html(first, "^<em>$") and #panels > 0 then
        for i, p in ipairs(panels) do
          local fig = (i == #panels) and em_text(b.content) or nil
          out:insert(pandoc.RawBlock("latex", panel_latex(p.src, p.caption, fig)))
        end
        panels = {}
        goto continue
      end
    end

    out:insert(b)
    ::continue::
  end
  doc.blocks = out
  return doc
end
