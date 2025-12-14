-- Pandoc Lua filter: replace common emoji with ASCII text for PDF builds.
--
-- LaTeX engines can fail on emoji depending on font support.
-- We normalize common emoji used in this repo's docs.

local replacements = {
  ["✅"] = "[OK]",
  ["☑️"] = "[x]",
  ["☑"] = "[x]",
  ["❌"] = "[no]",
  ["⚠️"] = "[WARNING]",
  ["⚠"] = "[WARNING]",
  ["🔒"] = "[LOCK]",
  ["🔄"] = "[ROTATE]",
  ["🎯"] = "[TARGET]",
  ["🗄️"] = "[STORAGE]",
  ["🗄"] = "[STORAGE]",
  ["🚫"] = "[NO]",
  ["👥"] = "[USERS]",
  ["🚀"] = "",
}

function Str(el)
  local text = el.text
  local changed = false

  for k, v in pairs(replacements) do
    if text:find(k, 1, true) then
      text = text:gsub(k, v)
      changed = true
    end
  end

  if changed then
    return pandoc.Str(text)
  end

  return nil
end
