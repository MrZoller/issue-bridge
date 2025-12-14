-- Pandoc Lua filter: drop SVG images for LaTeX/PDF builds.
--
-- Pandoc+LaTeX often requires extra tooling/packages to render SVG.
-- For our docs PDFs, it's fine to omit SVG images (e.g. README badges).

function Image(img)
  local src = img.src
  if src == nil then
    -- Compatibility with older pandoc versions
    src = img[1]
  end

  if type(src) == "string" and src:match("%.svg([?#].*)?$") then
    return {}
  end

  return img
end
