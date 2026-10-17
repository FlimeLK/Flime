-- Hud: верхня панель валют, нижнє меню кнопок, підказки навчання
-- та перемикання вікон (одночасно відкрите лише одне).

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local GameMath = require(Shared:WaitForChild("GameMath"))
local CombatConfig = require(Shared:WaitForChild("Config"):WaitForChild("CombatConfig"))
local ShopConfig = require(Shared:WaitForChild("Config"):WaitForChild("ShopConfig"))

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

-- Червона позначка "!" на кнопці меню (наприклад, є нагорода в Quests).
function Hud.SetBadge(name, visible)
	local button = menuButtons[name]
	if not button then
		return
	end
	local badge = button:FindFirstChild("Badge")
	if not badge then
		badge = UIKit.Label({
			Name = "Badge",
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.new(1, -4, 0, 4),
			Size = UDim2.fromOffset(24, 24),
			BackgroundColor3 = UIKit.Colors.Danger,
			Font = UIKit.Font,
			TextSize = 16,
			Text = "!",
			ZIndex = 5,
			Parent = button,
		})
		UIKit.Corner(badge, 12)
	end
	badge.Visible = visible
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
	-- Дохід залежить і від часу (буст може закінчитись), тому оновлюємо щосекунди
	local function updateIncome()
		local data = ClientState.Data
		if data then
			incomeLabel.Text = "+" .. GameMath.FormatNumber(GameMath.GetTotalIncome(data, workspace:GetServerTimeNow())) .. "/s"
		end
	end
	ClientState.OnDataChanged(updateIncome)
	task.spawn(function()
		while true do
			task.wait(1)
			updateIncome()
		end
	end)
end

-- Активні бусти (зілля) у верхньому лівому куті з таймером
local function buildBoostBar(gui)
	local bar = UIKit.Create("Frame", {
		Name = "Boosts",
		Position = UDim2.fromOffset(10, 8),
		Size = UDim2.fromOffset(190, 70),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 4), SortOrder = Enum.SortOrder.LayoutOrder, Parent = bar })
	local labels = {}
	local order = 0
	for boostId, boost in ShopConfig.Boosts do
		order += 1
		local label = UIKit.Label({
			LayoutOrder = order,
			Size = UDim2.fromOffset(190, 30),
			BackgroundColor3 = UIKit.Colors.Background,
			BackgroundTransparency = 0.2,
			Font = UIKit.Font,
			TextSize = 17,
			TextColor3 = UIKit.Colors.Success,
			Visible = false,
			Parent = bar,
		})
		UIKit.Corner(label, 8)
		labels[boostId] = { label = label, boost = boost }
	end
	task.spawn(function()
		while true do
			local data = ClientState.Data
			local now = workspace:GetServerTimeNow()
			for boostId, entry in labels do
				local active = data ~= nil and GameMath.IsBoostActive(data, boostId, now)
				entry.label.Visible = active
				if active then
					entry.label.Text = ("%s ×%d  %s"):format(entry.boost.displayName, entry.boost.multiplier, GameMath.FormatTime(data.boosts[boostId] - now))
				end
			end
			task.wait(1)
		end
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

	local function teamIsEmpty(data)
		for i = 1, CombatConfig.TeamSize do
			if data.team[i] ~= "" then
				return false
			end
		end
		return true
	end

	updateHint = function()
		local data = ClientState.Data
		local text = nil
		if not data then
			text = nil
		elseif not data.tutorial.freeRollUsed then
			text = "👉 Натисни 🎲 Roll і зроби перший БЕЗКОШТОВНИЙ кидок!"
		elseif not data.tutorial.completed then
			text = "👉 Відкрий 🎒 Inventory, вибери героя і натисни Place"
		elseif teamIsEmpty(data) and data.totalRolls >= 5 and data.stats.enemiesDefeated == 0 then
			text = "⚔️ Збери команду в Team і вирушай у 🌍 Worlds → Ninja Village"
		end
		if text then
			hint.Text = text
		end
		hint.Visible = text ~= nil and not anyPanelOpen()
	end
	ClientState.OnDataChanged(function()
		updateHint()
	end)
end

function Hud.Init(gui)
	buildTopBar(gui)
	buildBoostBar(gui)
	buildMenu(gui)
	buildTutorialHint(gui)
end

return Hud
