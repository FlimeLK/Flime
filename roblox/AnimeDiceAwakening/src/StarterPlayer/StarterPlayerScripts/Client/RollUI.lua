-- RollUI: вікно кубиків (вибір кубика, шанси, гарантія), кнопки Roll / Auto / Skip
-- та анімація кидка. Анімація показує результат, який УЖЕ визначив сервер.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local DiceConfig = require(Config:WaitForChild("DiceConfig"))
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local RollUI = {}

local selectedDice = "Basic"
local rolling = false
local autoRolling = false
local lastRequestTime = 0
local skipRequested = false

local ui: { [string]: any } = {} -- посилання на елементи інтерфейсу

---------------------------------------------------------------------
-- Анімація кидка
---------------------------------------------------------------------

local function buildOverlay(gui)
	local overlay = UIKit.Create("TextButton", {
		Name = "RollOverlay",
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Color3.new(0, 0, 0),
		BackgroundTransparency = 0.35,
		AutoButtonColor = false,
		Text = "",
		Visible = false,
		ZIndex = 40,
		Parent = gui,
	})
	overlay.Activated:Connect(function()
		skipRequested = true
	end)

	local flash = UIKit.Create("Frame", {
		Name = "Flash",
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BackgroundTransparency = 1,
		Parent = overlay,
	})

	local stage = UIKit.Create("Frame", {
		Name = "Stage",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(460, 440),
		BackgroundTransparency = 1,
		Parent = overlay,
	})
	UIKit.AddScale(stage)

	-- Промені за карткою (два квадрати, що обертаються)
	local rays = {}
	for i = 1, 2 do
		local ray = UIKit.Create("Frame", {
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.fromScale(0.5, 0.45),
			Size = UDim2.fromOffset(300, 300),
			BackgroundTransparency = 0.55,
			Rotation = i * 45,
			Visible = false,
			Parent = stage,
		})
		UIKit.Corner(ray, 30)
		rays[i] = ray
	end

	local die = UIKit.Create("Frame", {
		Name = "Die",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.42),
		Size = UDim2.fromOffset(170, 170),
		BackgroundColor3 = Color3.new(1, 1, 1),
		Parent = stage,
	})
	UIKit.Corner(die, 28)
	local dieStroke = UIKit.Stroke(die, Color3.fromRGB(30, 20, 50), 6)
	local dieLabel = UIKit.Label({
		Size = UDim2.fromScale(1, 1),
		Font = UIKit.Font,
		TextSize = 110,
		TextColor3 = Color3.fromRGB(40, 30, 70),
		Text = "?",
		Parent = die,
	})

	local card = UIKit.Create("Frame", {
		Name = "Card",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.45),
		Size = UDim2.fromOffset(420, 270),
		BackgroundColor3 = UIKit.Colors.Panel,
		Visible = false,
		Parent = stage,
	})
	UIKit.Corner(card, 20)
	local cardStroke = UIKit.Stroke(card, Color3.new(1, 1, 1), 4)
	local cardPop = UIKit.Create("UIScale", { Parent = card })

	local function cardLabel(name, y, height, size, font)
		return UIKit.Label({
			Name = name,
			Position = UDim2.fromOffset(12, y),
			Size = UDim2.new(1, -24, 0, height),
			Font = font or UIKit.BodyFont,
			TextSize = size,
			Text = "",
			Parent = card,
		})
	end
	local rarityLabel = cardLabel("Rarity", 10, 32, 28, UIKit.Font)
	local nameLabel = cardLabel("HeroName", 42, 44, 34, UIKit.Font)
	local typeLabel = cardLabel("Type", 88, 24, 18)
	local statsLabel = cardLabel("Stats", 114, 24, 18)
	local abilityLabel = cardLabel("Ability", 142, 60, 16)
	abilityLabel.TextColor3 = UIKit.Colors.SubText
	local badgeLabel = cardLabel("Badges", 210, 40, 24, UIKit.Font)
	badgeLabel.TextColor3 = UIKit.Colors.Gold

	local hint = UIKit.Label({
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.fromScale(0.5, 1),
		Size = UDim2.fromOffset(440, 30),
		TextColor3 = UIKit.Colors.SubText,
		Text = "Натисни, щоб пропустити",
		Parent = stage,
	})

	ui.overlay = {
		root = overlay,
		flash = flash,
		rays = rays,
		die = die,
		dieStroke = dieStroke,
		dieLabel = dieLabel,
		card = card,
		cardStroke = cardStroke,
		cardPop = cardPop,
		rarityLabel = rarityLabel,
		nameLabel = nameLabel,
		typeLabel = typeLabel,
		statsLabel = statsLabel,
		abilityLabel = abilityLabel,
		badgeLabel = badgeLabel,
		hint = hint,
	}
end

local function fillCard(result, heroDef, rarityInfo)
	local o = ui.overlay
	o.rarityLabel.Text = result.rarity
	o.rarityLabel.TextColor3 = rarityInfo.color
	o.nameLabel.Text = heroDef.name
	o.nameLabel.TextColor3 = rarityInfo.color:Lerp(Color3.new(1, 1, 1), 0.4)
	o.typeLabel.Text = ("%s %s • %s"):format(HeroConfig.ElementIcons[heroDef.element] or "", heroDef.element, heroDef.archetype)
	o.statsLabel.Text = ("⚔️ %s   ⏱ %.1f/s   🪙 +%s/s"):format(
		GameMath.FormatNumber(heroDef.damage),
		heroDef.attackSpeed,
		GameMath.FormatNumber(heroDef.income)
	)
	o.abilityLabel.Text = ("✦ %s: %s"):format(heroDef.ability.name, heroDef.ability.description)
	local badges = {}
	if result.isNew then
		table.insert(badges, "🆕 NEW!")
	end
	if result.pity then
		table.insert(badges, "🎯 Гарантія!")
	end
	if result.free then
		table.insert(badges, "🎁 Безкоштовно")
	end
	o.badgeLabel.Text = table.concat(badges, "   ")
	o.cardStroke.Color = rarityInfo.color
end

local function waitOrSkip(seconds)
	local start = os.clock()
	while os.clock() - start < seconds and not skipRequested do
		task.wait(0.03)
	end
	local skipped = skipRequested
	skipRequested = false
	return skipped
end

local function playReveal(result)
	local heroDef = HeroConfig.Heroes[result.heroId]
	local rarityInfo = RarityConfig.Info[result.rarity]
	if not heroDef or not rarityInfo then
		return
	end

	-- Режим без анімації: лише коротке повідомлення
	if ClientState.GetSetting("skipAnimations") then
		local text = ("%s%s — %s"):format(if result.isNew then "🆕 " else "", heroDef.name, result.rarity)
		UIKit.Toast(text, "rarity", rarityInfo.color:Lerp(Color3.new(0, 0, 0), 0.35))
		task.wait(0.3)
		return
	end

	local o = ui.overlay
	local effects = ClientState.GetSetting("effects")
	local dice = DiceConfig.Dice[selectedDice]
	skipRequested = false
	o.root.Visible = true
	o.card.Visible = false
	o.die.Visible = true
	o.die.BackgroundColor3 = dice and dice.color or Color3.new(1, 1, 1)
	o.dieStroke.Color = Color3.fromRGB(30, 20, 50)
	for _, ray in o.rays do
		ray.Visible = false
	end

	-- 1. Кубик крутиться. Для Legendary+ довше й змінює колір — інтрига.
	local rare = rarityInfo.rank >= 4
	local spinTime = if rare then 1.8 else 1.0
	local start = os.clock()
	while os.clock() - start < spinTime and not skipRequested do
		o.die.Rotation = (o.die.Rotation + 24) % 360
		o.dieLabel.Text = tostring(math.random(1, 6))
		if rare and os.clock() - start > spinTime * 0.5 then
			o.die.BackgroundColor3 = rarityInfo.color
			o.dieStroke.Color = Color3.new(1, 1, 1)
		end
		task.wait(0.05)
	end
	skipRequested = false
	o.die.Rotation = 0
	o.die.Visible = false

	-- 2. Показ картки героя
	fillCard(result, heroDef, rarityInfo)
	o.card.Visible = true
	o.cardPop.Scale = 0.3
	TweenService:Create(o.cardPop, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1 }):Play()

	if effects and rarityInfo.rank >= 3 then
		for _, ray in o.rays do
			ray.BackgroundColor3 = rarityInfo.color
			ray.Visible = true
			TweenService:Create(ray, TweenInfo.new(3, Enum.EasingStyle.Linear), { Rotation = ray.Rotation + 180 }):Play()
		end
	end
	if effects and rare then
		o.flash.BackgroundTransparency = 0.1
		TweenService:Create(o.flash, TweenInfo.new(0.6), { BackgroundTransparency = 1 }):Play()
	end

	waitOrSkip(if autoRolling then 1.0 else 2.5)
	o.root.Visible = false
end

---------------------------------------------------------------------
-- Кидок
---------------------------------------------------------------------

local function doRoll()
	if rolling then
		return false
	end
	rolling = true
	-- Не надсилаємо запит частіше, ніж дозволяє сервер
	local waitFor = EconomyConfig.RollCooldown + 0.05 - (os.clock() - lastRequestTime)
	if waitFor > 0 then
		task.wait(waitFor)
	end
	lastRequestTime = os.clock()
	local result = ClientState.Request("RollDice", selectedDice)
	if not result.ok then
		UIKit.Toast(result.message or "Не вдалося кинути кубик", "error")
		rolling = false
		return false
	end
	playReveal(result)
	rolling = false
	return true
end

local refreshButtons -- оголошена нижче

local function setAuto(enabled)
	autoRolling = enabled
	refreshButtons()
	if enabled then
		task.spawn(function()
			while autoRolling do
				if rolling then
					task.wait(0.1)
				elseif not doRoll() then
					autoRolling = false
					refreshButtons()
				else
					task.wait(0.1)
				end
			end
		end)
	end
end

---------------------------------------------------------------------
-- Вікно кубиків
---------------------------------------------------------------------

local function isDiceUnlocked(data, dice)
	return data ~= nil and (GameMath.IsDiceUnlocked(data, dice))
end

local function refreshInfo()
	local data = ClientState.Data
	local dice = DiceConfig.Dice[selectedDice]
	local playerLuck = if data then GameMath.GetLuck(data, workspace:GetServerTimeNow()) else 1
	ui.diceTitle.Text = dice.icon .. " " .. dice.displayName
	ui.diceDesc.Text = ("%s Удача: ×%.2f%s"):format(dice.description, dice.luck * playerLuck, if playerLuck > 1 then " 🍀 зілля активне!" else "")

	local chances = GameMath.GetChances(dice, playerLuck)
	for _, rarity in RarityConfig.Order do
		ui.chanceLabels[rarity].Text = GameMath.FormatChance(chances[rarity])
	end

	if data then
		local lines = {}
		for _, info in GameMath.GetPityRemaining(data) do
			table.insert(lines, ("🎯 %s+ гарантовано щонайпізніше через %d кидк."):format(info.rarity, info.remaining))
		end
		ui.pityLabel.Text = table.concat(lines, "\n")
	end
end

function refreshButtons()
	local data = ClientState.Data
	for diceId, button in ui.diceButtons do
		local dice = DiceConfig.Dice[diceId]
		local unlocked = isDiceUnlocked(data, dice)
		if unlocked then
			button.Text = ("%s %s\n🪙 %s"):format(dice.icon, dice.displayName, GameMath.FormatNumber(dice.price))
		else
			local requirement = if data then select(2, GameMath.IsDiceUnlocked(data, dice)) else "..."
			button.Text = ("🔒 %s\n%s"):format(dice.displayName, requirement)
		end
		button.BackgroundColor3 = if unlocked then dice.color:Lerp(UIKit.Colors.Panel, 0.45) else UIKit.Colors.Disabled
		local stroke = button:FindFirstChildOfClass("UIStroke")
		stroke.Color = if diceId == selectedDice then Color3.new(1, 1, 1) else Color3.fromRGB(20, 15, 35)
		stroke.Thickness = if diceId == selectedDice then 4 else 2
	end

	local dice = DiceConfig.Dice[selectedDice]
	local free = data ~= nil and not data.tutorial.freeRollUsed and selectedDice == DiceConfig.TutorialDice
	if free then
		ui.rollButton.Text = "ROLL\n🎁 FREE!"
		ui.rollButton.BackgroundColor3 = UIKit.Colors.Success
	else
		ui.rollButton.Text = "ROLL\n🪙 " .. GameMath.FormatNumber(dice.price)
		local canAfford = ClientState.Coins >= dice.price and isDiceUnlocked(data, dice)
		ui.rollButton.BackgroundColor3 = if canAfford then UIKit.Colors.Accent else UIKit.Colors.Disabled
	end

	local autoUnlocked = data ~= nil and data.tutorial.completed
	if not autoUnlocked then
		ui.autoButton.Text = "🔒 Auto"
		ui.autoButton.BackgroundColor3 = UIKit.Colors.Disabled
	else
		ui.autoButton.Text = if autoRolling then "Auto: ON" else "Auto: OFF"
		ui.autoButton.BackgroundColor3 = if autoRolling then UIKit.Colors.Success else UIKit.Colors.PanelLight
	end

	local skip = ClientState.GetSetting("skipAnimations")
	ui.skipButton.Text = if skip then "⏩ Skip: ON" else "⏩ Skip: OFF"
	ui.skipButton.BackgroundColor3 = if skip then UIKit.Colors.Success else UIKit.Colors.PanelLight
end

local function buildPanel(gui)
	local panel, content = UIKit.Panel(gui, "Roll", "🎲 Dice")
	ui.panel = panel
	Hud.RegisterPanel("Roll", panel)

	-- Ліва колонка: список кубиків
	local list = UIKit.Create("Frame", {
		Size = UDim2.new(0, 220, 1, 0),
		BackgroundTransparency = 1,
		Parent = content,
	})
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, Parent = list })
	ui.diceButtons = {}
	for index, diceId in DiceConfig.Order do
		ui.diceButtons[diceId] = UIKit.Button({
			LayoutOrder = index,
			Size = UDim2.new(1, 0, 0, 56),
			TextSize = 18,
			Parent = list,
		}, function()
			selectedDice = diceId
			refreshInfo()
			refreshButtons()
		end)
	end

	-- Права колонка: інформація та шанси
	local info = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(236, 0),
		Size = UDim2.new(1, -236, 1, -72),
		BackgroundTransparency = 1,
		Parent = content,
	})
	ui.diceTitle = UIKit.Label({
		Size = UDim2.new(1, 0, 0, 32),
		Font = UIKit.Font,
		TextSize = 26,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = info,
	})
	ui.diceDesc = UIKit.Label({
		Position = UDim2.fromOffset(0, 32),
		Size = UDim2.new(1, 0, 0, 24),
		TextSize = 15,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = info,
	})

	local chancesFrame = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(0, 62),
		Size = UDim2.new(1, 0, 0, 160),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.3,
		Parent = info,
	})
	UIKit.Corner(chancesFrame, 12)
	UIKit.Create("UIGridLayout", {
		CellSize = UDim2.new(0.5, -8, 0, 46),
		CellPadding = UDim2.fromOffset(8, 6),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = chancesFrame,
	})
	UIKit.Create("UIPadding", {
		PaddingTop = UDim.new(0, 6),
		PaddingLeft = UDim.new(0, 8),
		Parent = chancesFrame,
	})
	ui.chanceLabels = {}
	for index, rarity in RarityConfig.Order do
		local row = UIKit.Create("Frame", { LayoutOrder = index, BackgroundTransparency = 1, Parent = chancesFrame })
		UIKit.Label({
			Size = UDim2.fromScale(0.6, 1),
			Font = UIKit.Font,
			TextSize = 20,
			TextColor3 = RarityConfig.GetColor(rarity),
			TextXAlignment = Enum.TextXAlignment.Left,
			Text = rarity,
			Parent = row,
		})
		ui.chanceLabels[rarity] = UIKit.Label({
			Position = UDim2.fromScale(0.6, 0),
			Size = UDim2.fromScale(0.4, 1),
			Font = UIKit.Font,
			TextSize = 20,
			TextXAlignment = Enum.TextXAlignment.Right,
			Parent = row,
		})
	end

	ui.pityLabel = UIKit.Label({
		Position = UDim2.fromOffset(0, 228),
		Size = UDim2.new(1, 0, 0, 50),
		TextSize = 15,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = info,
	})

	-- Кнопки внизу
	local buttons = UIKit.Create("Frame", {
		AnchorPoint = Vector2.new(0, 1),
		Position = UDim2.new(0, 236, 1, 0),
		Size = UDim2.new(1, -236, 0, 64),
		BackgroundTransparency = 1,
		Parent = content,
	})
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		Padding = UDim.new(0, 8),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = buttons,
	})
	ui.rollButton = UIKit.Button({ LayoutOrder = 1, Size = UDim2.fromOffset(210, 64), TextSize = 22 }, function()
		task.spawn(doRoll)
	end)
	ui.rollButton.Parent = buttons
	ui.autoButton = UIKit.Button({ LayoutOrder = 2, Size = UDim2.fromOffset(130, 64), TextSize = 20 }, function()
		local data = ClientState.Data
		if not (data and data.tutorial.completed) then
			UIKit.Toast("Auto Roll відкриється після навчання: постав героя на базу", "info")
			return
		end
		setAuto(not autoRolling)
	end)
	ui.autoButton.Parent = buttons
	ui.skipButton = UIKit.Button({ LayoutOrder = 3, Size = UDim2.fromOffset(152, 64), TextSize = 19 }, function()
		ClientState.SetSetting("skipAnimations", not ClientState.GetSetting("skipAnimations"))
	end)
	ui.skipButton.Parent = buttons
end

function RollUI.Init(gui)
	buildPanel(gui)
	buildOverlay(gui)
	refreshInfo()
	refreshButtons()
	ClientState.OnDataChanged(function()
		refreshInfo()
		refreshButtons()
	end)
	ClientState.OnCurrencyChanged(function()
		refreshButtons()
	end)
	ClientState.OnSettingChanged(function()
		refreshButtons()
	end)
	-- Зілля удачі може закінчитись — оновлюємо шанси, поки вікно відкрите
	task.spawn(function()
		while true do
			task.wait(2)
			if ui.panel and ui.panel.Visible then
				refreshInfo()
			end
		end
	end)
end

return RollUI
