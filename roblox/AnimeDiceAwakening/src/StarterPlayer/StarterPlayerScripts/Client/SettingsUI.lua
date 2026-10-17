-- SettingsUI: перемикачі звуку, ефектів і пропуску анімацій.
-- Налаштування зберігаються на сервері разом із прогресом.

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local SettingsUI = {}

local OPTIONS = {
	{ key = "sound", title = "🔊 Звук", hint = "Звуки кидків і нагород (з'являться на наступному етапі)" },
	{ key = "effects", title = "✨ Ефекти", hint = "Аури героїв, спалахи й промені рідкісних випадінь" },
	{ key = "skipAnimations", title = "⏩ Пропуск анімацій", hint = "Показувати результат кидка одразу" },
}

local toggles = {}

local function refresh()
	for key, button in toggles do
		local enabled = ClientState.GetSetting(key)
		button.Text = if enabled then "ON" else "OFF"
		button.BackgroundColor3 = if enabled then UIKit.Colors.Success else UIKit.Colors.Disabled
	end
end

function SettingsUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Settings", "⚙️ Settings")
	Hud.RegisterPanel("Settings", panel)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 10), SortOrder = Enum.SortOrder.LayoutOrder, Parent = content })

	for index, option in OPTIONS do
		local row = UIKit.Create("Frame", {
			LayoutOrder = index,
			Size = UDim2.new(1, 0, 0, 80),
			BackgroundColor3 = UIKit.Colors.Background,
			BackgroundTransparency = 0.3,
			Parent = content,
		})
		UIKit.Corner(row, 14)
		UIKit.Label({
			Position = UDim2.fromOffset(16, 6),
			Size = UDim2.new(1, -200, 0, 36),
			Font = UIKit.Font,
			TextSize = 24,
			TextXAlignment = Enum.TextXAlignment.Left,
			Text = option.title,
			Parent = row,
		})
		UIKit.Label({
			Position = UDim2.fromOffset(16, 42),
			Size = UDim2.new(1, -200, 0, 30),
			TextSize = 15,
			TextColor3 = UIKit.Colors.SubText,
			TextXAlignment = Enum.TextXAlignment.Left,
			Text = option.hint,
			Parent = row,
		})
		toggles[option.key] = UIKit.Button({
			AnchorPoint = Vector2.new(1, 0.5),
			Position = UDim2.new(1, -16, 0.5, 0),
			Size = UDim2.fromOffset(140, 56),
			TextSize = 24,
			Parent = row,
		}, function()
			ClientState.SetSetting(option.key, not ClientState.GetSetting(option.key))
		end)
	end

	refresh()
	ClientState.OnDataChanged(refresh)
	ClientState.OnSettingChanged(refresh)
end

return SettingsUI
