-- Hud: верхня панель валют, нижнє меню кнопок, підказки навчання
-- та перемикання вікон (одночасно відкрите лише одне).

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))

local Hud = {}

local panels = {} -- [name] = Frame
local menuButtons = {}

local MENU = {
	{ name = "Roll", text = "🎲 Roll", color = Color3.fromRGB(255, 110, 200) },
	{ name = "Inventory", text = "🎒 Inventory", color = Color3.fromRGB(110, 170, 255) },
	{ name = "Team", text = "⚔️ Team", color = Color3.fromRGB(255, 140, 80) },
	{ name = "Upgrades", text = "⬆️ Upgrades", color = Color3.fromRGB(90, 210, 130) },
	{ name = "Quests", text = "📜 Quests", color = Color3.fromRGB(255, 200, 70) },
	{ name = "Worlds", text = "🌍 Worlds", color = Color3.fromRGB(150, 110, 255) },
	{ name = "Settings", text = "⚙️", color = Color3.fromRGB(120, 120, 150), width = 64 },
}

local updateHint = function() end

function Hud.RegisterPanel(name, panel)
	panels[name] = panel
	-- Підказка навчання ховається, поки відкрите будь-яке вікно
	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		updateHint()
	end)
end

local function anyPanelOpen()
	for _, panel in panels do
		if panel.Visible then
			return true
		end
	end
	return false
end

function Hud.TogglePanel(name)
	local target = panels[name]
	if not target then
		return
	end
	local open = not target.Visible
	for _, panel in panels do
		panel.Visible = false
	end
	target.Visible = open
end

function Hud.GetMenuButton(name)
	return menuButtons[name]
end

local function buildTopBar(gui)
	local bar = UIKit.Create("Frame", {
		Name = "TopBar",
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 8),
		Size = UDim2.fromOffset(560, 52),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		Padding = UDim.new(0, 10),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = bar,
	})

	local function counter(order, width, color)
		local label = UIKit.Label({
			LayoutOrder = order,
			Size = UDim2.fromOffset(width, 52),
			BackgroundColor3 = UIKit.Colors.Background,
			BackgroundTransparency = 0.15,
			Font = UIKit.Font,
			TextSize = 24,
			TextColor3 = color,
			Text = "...",
			Parent = bar,
		})
		UIKit.Corner(label, 14)
		UIKit.Stroke(label, color, 2)
		return label
	end

	local coinsLabel = counter(1, 200, UIKit.Colors.Gold)
	local crystalsLabel = counter(2, 150, UIKit.Colors.Accent2)
	local incomeLabel = counter(3, 180, UIKit.Colors.Success)

	ClientState.OnCurrencyChanged(function(coins, crystals)
		coinsLabel.Text = "🪙 " .. GameMath.FormatNumber(coins)
		crystalsLabel.Text = "💎 " .. GameMath.FormatNumber(crystals)
	end)
	ClientState.OnDataChanged(function(data)
		incomeLabel.Text = "+" .. GameMath.FormatNumber(GameMath.GetTotalIncome(data)) .. "/s"
	end)
end

local function buildMenu(gui)
	local bar = UIKit.Create("Frame", {
		Name = "MenuBar",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -8),
		Size = UDim2.fromOffset(880, 68),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.25,
		Parent = gui,
	})
	UIKit.Corner(bar, 16)
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		VerticalAlignment = Enum.VerticalAlignment.Center,
		Padding = UDim.new(0, 8),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = bar,
	})
	for index, entry in MENU do
		menuButtons[entry.name] = UIKit.Button({
			Name = entry.name,
			LayoutOrder = index,
			Size = UDim2.fromOffset(entry.width or 122, 56),
			BackgroundColor3 = entry.color,
			Text = entry.text,
			TextSize = 19,
			Parent = bar,
		}, function()
			Hud.TogglePanel(entry.name)
		end)
	end
end

local function buildTutorialHint(gui)
	local hint = UIKit.Label({
		Name = "TutorialHint",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -88),
		Size = UDim2.fromOffset(620, 46),
		BackgroundColor3 = UIKit.Colors.Gold,
		Font = UIKit.Font,
		TextSize = 21,
		TextColor3 = Color3.fromRGB(40, 25, 10),
		Visible = false,
		Parent = gui,
	})
	UIKit.Corner(hint, 12)
	UIKit.AddScale(hint)

	updateHint = function()
		local data = ClientState.Data
		if not data or data.tutorial.completed then
			hint.Visible = false
			return
		end
		if not data.tutorial.freeRollUsed then
			hint.Text = "👉 Натисни 🎲 Roll і зроби перший БЕЗКОШТОВНИЙ кидок!"
		else
			hint.Text = "👉 Відкрий 🎒 Inventory, вибери героя і натисни Place"
		end
		hint.Visible = not anyPanelOpen()
	end
	ClientState.OnDataChanged(function()
		updateHint()
	end)
end

-- Вікна, які з'являться на наступних етапах
local COMING_SOON = {
	Team = "Команда з 3 героїв, що б'ються поруч із тобою.\nЗ'явиться на етапі 2 разом з першим світом.",
	Quests = "Завдання з нагородами в Coins і Crystals.\nЗ'являться на етапі 3.",
	Worlds = "Ninja Village • Pirate Island • Demon Night City\nMagic Academy • Sky Arena\n\nПерший світ відкриється на етапі 2.",
}

local function buildComingSoon(gui)
	for name, text in COMING_SOON do
		local panel, content = UIKit.Panel(gui, name, name)
		UIKit.Label({
			Size = UDim2.fromScale(1, 1),
			Font = UIKit.Font,
			TextSize = 24,
			TextColor3 = UIKit.Colors.SubText,
			Text = "🚧 Скоро!\n\n" .. text,
			Parent = content,
		})
		Hud.RegisterPanel(name, panel)
	end
end

function Hud.Init(gui)
	buildTopBar(gui)
	buildMenu(gui)
	buildTutorialHint(gui)
	buildComingSoon(gui)
end

return Hud
