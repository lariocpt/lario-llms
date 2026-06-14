--- @sync entry
return {
	entry = function()
		local h = cx.active.current.hovered
		local is_dir = h and h.cha.is_dir or false

		if is_dir then
			ya.emit("enter", {})
			ya.emit("quit", {})
		else
			ya.emit("open", { hovered = true })
		end
	end,
}
