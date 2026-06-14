local is_dir = ya.sync(function()
      local h = cx.active.current.hovered
      return h and h.cha.is_dir or false
end)

return {
      entry = function()
              if is_dir() then
                      ya.mgr_emit("enter", {})
                      ya.mgr_emit("quit", {})
              else
                      ya.mgr_emit("open", { hovered = true })   -- open the hovered file
              end
      end,
}
