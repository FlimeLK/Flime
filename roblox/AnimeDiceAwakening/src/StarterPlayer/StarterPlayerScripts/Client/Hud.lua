-- Hud: головний екран у стилі аніме-симуляторів.
--
--   зверху по центру     — 🌍 Worlds / 🏠 Home / 💎 Shop
--   ліворуч              — великі кнопки 📜 Quests, ♻️ Rebirth, 📖 Index
--   внизу по центру      — ⚔️ Team, 🎒 Backpack, великий 🎲 ROLL, ⬆️ Upgrades
--   над ROLL             — вибір кубика
--   внизу ліворуч        — гроші, кристали й дохід
--   внизу праворуч       — Auto Roll і поточна удача 🍀
--   вгорі праворуч       — ⚙️ та активні зілля
--
-- Інші модулі змінюють поведінку кнопок через Hud.SetAction і читають їх через Hud.Get.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local GameMath = require(Shared:WaitForChild("GameMath"))
local Config = Shared:WaitForChild("Config")
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))

local Hud = {}

local panels = {} -- [name] = Frame
local elements = {} -- [name] = кнопка або напис
local actions = {} -- [name] = функція, що замінює стандартну дію кнопки

-- Кнопка відкриває вікно з такою назвою (якщо назви різні)
local PANEL_FOR = {
	Backpack = "Inventory",
	Dice = "Roll",
	Index = "Quests",
}

local COLORS = {
	Worlds = Color3.fromRGB(255, 185, 40),
	Home = Color3.fromRGB(60, 165, 255),
	Shop = Color3.fromRGB(60, 205, 85),
	Quests = Color3.fromRGB(255, 150, 40),
	Rebirth = Color3.fromRGB(255, 65, 90),
	Index = Color3.fromRGB(70, 130, 255),
	Team = Color3.fromRGB(255, 120, 60),
	Backpack = Color3.fromRGB(135, 85, 255),
	Roll = Color3.fromRGB(190, 70, 255),
	Upgrades = Color3.fromRGB(70, 205, 100),
	Settings = Color3.fromRGB(110, 110, 150),
}
Hud.Colors = COLORS

local updateHint = function() end

local function anyPanelOpen()
	for _, panel in panels do
		if panel.Visible then
			return true
		end
	end
	return false
end

function Hud.RegisterPanel(name, panel)
	panels[name] = panel
	-- Підказка навчання ховається, поки відкрите будь-яке вікно
	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		updateHint()
	end)
end

function Hud.OpenPanel(name)
	for panelName, panel in panels do
		panel.Visible = panelName == name
	end
end

function Hud.TogglePanel(name)
	local target = panels[name]
	if not target then
		return
	end
	if target.Visible then
		target.Visible = false
	else
		Hud.OpenPanel(name)
	end
end

function Hud.IsPanelOpen(name)
	return panels[name] ~= nil and panels[name].Visible
end

-- Замінити дію кнопки (наприклад, ROLL кидає кубик, а не відкриває вікно).
function Hud.SetAction(name, callback)
	actions[name] = callback
end

-- Кнопка або напис головного екрана за назвою.
function Hud.Get(name)
	return elements[name]
end

Hud.GetMenuButton = Hud.Get

-- Червона позначка на кнопці: true — "!", число — лічильник, false — сховати.
function Hud.SetBadge(name, value)
	local button = elements[name]
	if button then
		UIKit.SetBadge(button, value)
	end
end

local function press(name)
	if actions[name] then
		actions[name]()
	else
		Hud.TogglePanel(PANEL_FOR[name] or name)
	end
end

---------------------------------------------------------------------
-- Зверху: Worlds / Home / Shop
---------------------------------------------------------------------

local function buildTopNav(gui)
	local bar = UIKit.Create("Frame", {
		Name = "TopNav",
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 6),
		Size = UDim2.fromOffset(660, 66),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		Padding = UDim.new(0, 12),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = bar,
	})
	for index, entry in { { "Worlds", "🌍 Worlds" }, { "Home", "🏠 Home" }, { "Shop", "💎 Shop" } } do
		local name = entry[1]
		local button = UIKit.Button({
			Name = name,
			LayoutOrder = index,
			Size = UDim2.fromOffset(205, 62),
			BackgroundColor3 = COLORS[name],
			Text = entry[2],
			TextSize = 32,
			Parent = bar,
		}, function()
			press(name)
		end)
		button.TextOutline.Thickness = 3
		button.Outline.UIStroke.Thickness = 4
		elements[name] = button
	end
end

---------------------------------------------------------------------
-- Ліворуч: великі квадратні кнопки
---------------------------------------------------------------------

local function buildLeftColumn(gui)
	local column = UIKit.Create("Frame", {
		Name = "LeftButtons",
		AnchorPoint = Vector2.new(0, 0.5),
		Position = UDim2.new(0, 12, 0.5, -24),
		Size = UDim2.fromOffset(104, 336),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(column)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 12), SortOrder = Enum.SortOrder.LayoutOrder, Parent = column })
	for index, entry in { { "Quests", "📜", "Quests" }, { "Rebirth", "♻️", "Rebirth" }, { "Index", "📖", "Index" } } do
		local name = entry[1]
		elements[name] = UIKit.IconButton({
			Name = name,
			Icon = entry[2],
			Text = entry[3],
			Color = COLORS[name],
			Size = UDim2.fromOffset(104, 104),
			LayoutOrder = index,
			Parent = column,
		}, function()
			press(name)
		end)
	end
end

---------------------------------------------------------------------
-- Внизу по центру: Team, Backpack, ROLL, Upgrades + вибір кубика
---------------------------------------------------------------------

local function buildBottomBar(gui)
	local bar = UIKit.Create("Frame", {
		Name = "BottomBar",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -8),
		Size = UDim2.fromOffset(520, 146),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		VerticalAlignment = Enum.VerticalAlignment.Bottom,
		Padding = UDim.new(0, 14),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = bar,
	})
	local items = {
		{ "Team", "⚔️", "TEAM", 104 },
		{ "Backpack", "🎒", "BACKPACK", 104 },
		{ "Roll", "🎲", "ROLL", 142, "🎁 FREE" },
		{ "Upgrades", "⬆️", "UPGRADES", 104 },
	}
	for index, item in items do
		local name = item[1]
		elements[name] = UIKit.IconButton({
			Name = name,
			Icon = item[2],
			Text = item[3],
			Sub = item[5],
			Color = COLORS[name],
			Size = UDim2.fromOffset(item[4], item[4]),
			LayoutOrder = index,
			Parent = bar,
		}, function()
			press(name)
		end)
	end

	-- Іконка ROLL "дихає", щоб привертати увагу
	local rollScale = UIKit.Create("UIScale", { Parent = elements.Roll.Icon })
	TweenService:Create(rollScale, TweenInfo.new(0.8, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), { Scale = 1.12 }):Play()

	-- Вибір кубика над ROLL
	local dice = UIKit.Button({
		Name = "Dice",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -162),
		Size = UDim2.fromOffset(240, 40),
		BackgroundColor3 = UIKit.Colors.Panel,
		Text = "🎲 Basic Dice ▾",
		TextSize = 20,
		Parent = gui,
	}, function()
		press("Dice")
	end)
	UIKit.AddScale(dice)
	elements.Dice = dice
end

---------------------------------------------------------------------
-- Внизу ліворуч: гроші
---------------------------------------------------------------------

local function buildMoney(gui)
	local frame = UIKit.Create("Frame", {
		Name = "Money",
		AnchorPoint = Vector2.new(0, 1),
		Position = UDim2.new(0, 14, 1, -10),
		Size = UDim2.fromOffset(270, 110),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(frame)
	local coins = UIKit.Label({
		Name = "Coins",
		Size = UDim2.new(1, 0, 0, 62),
		Font = UIKit.Font,
		TextScaled = true,
		TextColor3 = UIKit.Colors.Money,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "🪙 ...",
		Outline = 4,
		Parent = frame,
	})
	UIKit.Shade(coins, 0.25)
	local crystals = UIKit.Label({
		Name = "Crystals",
		Position = UDim2.fromOffset(0, 64),
		Size = UDim2.fromOffset(120, 36),
		Font = UIKit.Font,
		TextScaled = true,
		TextColor3 = UIKit.Colors.Accent2,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "💎 0",
		Outline = 3,
		Parent = frame,
	})
	local income = UIKit.Label({
		Name = "Income",
		Position = UDim2.fromOffset(126, 64),
		Size = UDim2.fromOffset(144, 36),
		Font = UIKit.Font,
		TextScaled = true,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "⚡ +0/s",
		Outline = 3,
		Parent = frame,
	})
	elements.Coins, elements.Crystals, elements.Income = coins, crystals, income

	local lastCoins = nil
	ClientState.OnCurrencyChanged(function(coinsValue, crystalsValue)
		coins.Text = "🪙 " .. GameMath.FormatNumber(coinsValue)
		crystals.Text = "💎 " .. GameMath.FormatNumber(crystalsValue)
		-- Маленький "стрибок" при отриманні монет
		if lastCoins and coinsValue > lastCoins then
			coins.Size = UDim2.new(1, 0, 0, 68)
			TweenService:Create(coins, TweenInfo.new(0.2), { Size = UDim2.new(1, 0, 0, 62) }):Play()
		end
		lastCoins = coinsValue
	end)

	-- Дохід залежить і від часу (буст може закінчитись), тому оновлюємо щосекунди
	local function updateIncome()
		local data = ClientState.Data
		if data then
			income.Text = "⚡ +" .. GameMath.FormatNumber(GameMath.GetTotalIncome(data, workspace:GetServerTimeNow())) .. "/s"
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

---------------------------------------------------------------------
-- Внизу праворуч: Auto Roll та удача
---------------------------------------------------------------------

local function buildLuck(gui)
	local frame = UIKit.Create("Frame", {
		Name = "LuckArea",
		AnchorPoint = Vector2.new(1, 1),
		Position = UDim2.new(1, -14, 1, -10),
		Size = UDim2.fromOffset(160, 160),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(frame)
	elements.Auto = UIKit.Button({
		Name = "Auto",
		Size = UDim2.fromOffset(160, 46),
		BackgroundColor3 = UIKit.Colors.Disabled,
		Text = "🔒 AUTO",
		TextSize = 22,
		Parent = frame,
	}, function()
		press("Auto")
	end)
	UIKit.Label({
		Name = "Clover",
		Position = UDim2.fromOffset(30, 52),
		Size = UDim2.fromOffset(100, 66),
		TextScaled = true,
		Text = "🍀",
		Outline = 0,
		Parent = frame,
	})
	elements.Luck = UIKit.Label({
		Name = "Luck",
		Position = UDim2.fromOffset(0, 116),
		Size = UDim2.fromOffset(160, 40),
		Font = UIKit.Font,
		TextScaled = true,
		Text = "x1",
		Outline = 3,
		Parent = frame,
	})
end

---------------------------------------------------------------------
-- Вгорі праворуч: налаштування й зілля
---------------------------------------------------------------------

local function buildTopRight(gui)
	local settings = UIKit.Button({
		Name = "Settings",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -12, 0, 8),
		Size = UDim2.fromOffset(58, 58),
		BackgroundColor3 = COLORS.Settings,
		Text = "⚙️",
		TextSize = 32,
		Parent = gui,
	}, function()
		press("Settings")
	end)
	UIKit.AddScale(settings)
	elements.Settings = settings

	local bar = UIKit.Create("Frame", {
		Name = "Boosts",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -12, 0, 76),
		Size = UDim2.fromOffset(200, 80),
		BackgroundTransparency = 1,
		Parent = gui,
	})
	UIKit.AddScale(bar)
	UIKit.Create("UIListLayout", {
		Padding = UDim.new(0, 6),
		HorizontalAlignment = Enum.HorizontalAlignment.Right,
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = bar,
	})
	local labels = {}
	local order = 0
	for boostId, boost in ShopConfig.Boosts do
		order += 1
		local label = UIKit.Label({
			LayoutOrder = order,
			Size = UDim2.fromOffset(200, 34),
			BackgroundColor3 = UIKit.Colors.Success,
			BackgroundTransparency = 0,
			Font = UIKit.Font,
			TextSize = 18,
			Visible = false,
			Parent = bar,
		})
		UIKit.Corner(label, 10)
		UIKit.Stroke(label, UIKit.Colors.Outline, 3)
		UIKit.Shade(label, 0.25)
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

---------------------------------------------------------------------
-- Підказка навчання над кнопкою ROLL
---------------------------------------------------------------------

local function buildTutorialHint(gui)
	local hint = UIKit.Label({
		Name = "TutorialHint",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -212),
		Size = UDim2.fromOffset(600, 48),
		BackgroundColor3 = UIKit.Colors.Gold,
		BackgroundTransparency = 0,
		Font = UIKit.Font,
		TextSize = 22,
		Visible = false,
		Parent = gui,
	})
	UIKit.Corner(hint, 14)
	UIKit.Stroke(hint, UIKit.Colors.Outline, 3)
	UIKit.AddScale(hint)
	-- Підказка м'яко гойдається
	TweenService:Create(hint, TweenInfo.new(0.7, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), { Position = UDim2.new(0.5, 0, 1, -220) }):Play()

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
			text = "👇 Натисни великий 🎲 ROLL — перший кидок безкоштовний!"
		elseif not data.tutorial.completed then
			text = "👇 Відкрий 🎒 BACKPACK, вибери героя й натисни Place"
		elseif teamIsEmpty(data) and data.totalRolls >= 5 and data.stats.enemiesDefeated == 0 then
			text = "⚔️ Збери TEAM і вирушай у 🌍 Worlds → Ninja Village"
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
	buildTopNav(gui)
	buildLeftColumn(gui)
	buildBottomBar(gui)
	buildMoney(gui)
	buildLuck(gui)
	buildTopRight(gui)
	buildTutorialHint(gui)

	-- Home: повернення на свою базу з будь-якого світу
	Hud.SetAction("Home", function()
		local result = ClientState.Request("Travel", "Lobby")
		UIKit.Toast(result.message or "", if result.ok then "success" else "error")
	end)
end

return Hud
