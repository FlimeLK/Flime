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
local HeroModelBuilder = require(Shared:WaitForChild("HeroModelBuilder"))

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
-- Показ кидка: герої швидко змінюють один одного (як у слот-машині),
-- сповільнюються й зупиняються на тому, якого вже вибрав сервер.
-- Над героєм — шанс "1 in 52K", під ним — ім'я та рідкість, позаду — промені.
---------------------------------------------------------------------

local RAY_COUNT = 16
local rng = Random.new()

local function buildOverlay(gui)
	local overlay = UIKit.Create("TextButton", {
		Name = "RollOverlay",
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Color3.fromRGB(8, 18, 70),
		BackgroundTransparency = 0.18,
		AutoButtonColor = false,
		Text = "",
		Visible = false,
		ZIndex = 40,
		Parent = gui,
	})
	overlay.Activated:Connect(function()
		skipRequested = true
	end)
	UIKit.Create("UIGradient", {
		Color = ColorSequence.new(Color3.fromRGB(70, 120, 255), Color3.fromRGB(10, 20, 90)),
		Rotation = 90,
		Parent = overlay,
	})

	local flash = UIKit.Create("Frame", {
		Name = "Flash",
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BackgroundTransparency = 1,
		ZIndex = 5,
		Parent = overlay,
	})

	local stage = UIKit.Create("Frame", {
		Name = "Stage",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(900, 640),
		BackgroundTransparency = 1,
		Parent = overlay,
	})
	UIKit.AddScale(stage)

	-- Промені від центру
	local rays = UIKit.Create("Frame", {
		Name = "Rays",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.4),
		Size = UDim2.fromOffset(10, 10),
		BackgroundTransparency = 1,
		Parent = stage,
	})
	-- Кожен промінь — смуга через центр (GUI обертається навколо свого центру),
	-- яскрава посередині й прозора на кінцях: виходить "сонце" з RAY_COUNT променів.
	local rayParts = {}
	for i = 1, RAY_COUNT / 2 do
		local ray = UIKit.Create("Frame", {
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.fromScale(0.5, 0.5),
			Size = UDim2.fromOffset(if i % 2 == 0 then 70 else 40, 1150),
			Rotation = i * (360 / RAY_COUNT),
			BackgroundColor3 = Color3.new(1, 1, 1),
			BorderSizePixel = 0,
			Parent = rays,
		})
		UIKit.Create("UIGradient", {
			Transparency = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 1),
				NumberSequenceKeypoint.new(0.5, 0.35),
				NumberSequenceKeypoint.new(1, 1),
			}),
			Rotation = 90,
			Parent = ray,
		})
		rayParts[i] = ray
	end

	-- Кольорове сяйво позаду героя
	local glow = UIKit.Create("Frame", {
		Name = "Glow",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.4),
		Size = UDim2.fromOffset(380, 380),
		BackgroundColor3 = Color3.new(1, 1, 1),
		BackgroundTransparency = 0.45,
		Parent = stage,
	})
	UIKit.Create("UICorner", { CornerRadius = UDim.new(0.5, 0), Parent = glow })
	UIKit.Create("UIGradient", {
		Transparency = NumberSequence.new({ NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(0.7, 0.6), NumberSequenceKeypoint.new(1, 1) }),
		Rotation = 90,
		Parent = glow,
	})

	-- Сам герой — справжня 3D-модель у ViewportFrame
	local holder = UIKit.Create("Frame", {
		Name = "Holder",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.4),
		Size = UDim2.fromOffset(340, 340),
		BackgroundTransparency = 1,
		Parent = stage,
	})
	local pop = UIKit.Create("UIScale", { Parent = holder })
	local viewport = UIKit.Create("ViewportFrame", {
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		Ambient = Color3.fromRGB(190, 190, 210),
		LightColor = Color3.new(1, 1, 1),
		LightDirection = Vector3.new(-0.4, -1, 0.6),
		Parent = holder,
	})
	local camera = Instance.new("Camera")
	camera.FieldOfView = 40
	camera.Parent = viewport
	viewport.CurrentCamera = camera

	-- Білі "леза" з боків
	local glints = {}
	for side = -1, 1, 2 do
		local glint = UIKit.Create("Frame", {
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.new(0.5, side * 300, 0.4, 0),
			Size = UDim2.fromOffset(170, 14),
			BackgroundColor3 = Color3.new(1, 1, 1),
			Parent = stage,
		})
		UIKit.Create("UICorner", { CornerRadius = UDim.new(1, 0), Parent = glint })
		UIKit.Create("UIGradient", {
			Transparency = NumberSequence.new(if side < 0 then 0.9 else 0, if side < 0 then 0 else 0.9),
			Parent = glint,
		})
		glints[side] = glint
	end

	-- "1 in 52K" — нахилений, великий
	local odds = UIKit.Label({
		Name = "Odds",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.1),
		Size = UDim2.fromOffset(520, 90),
		Rotation = -10,
		Font = UIKit.Font,
		TextSize = 72,
		RichText = true,
		Text = "",
		Outline = 5,
		Parent = stage,
	})
	odds.TextOutline.Color = Color3.fromRGB(10, 20, 70)

	local name = UIKit.Label({
		Name = "HeroName",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.67),
		Size = UDim2.fromOffset(880, 90),
		Font = UIKit.Font,
		TextSize = 76,
		Text = "",
		Outline = 6,
		Parent = stage,
	})
	local rarity = UIKit.Label({
		Name = "Rarity",
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.77),
		Size = UDim2.fromOffset(800, 44),
		Font = UIKit.Font,
		TextSize = 38,
		RichText = true,
		Text = "",
		Outline = 4,
		Parent = stage,
	})

	-- Кругла кнопка AUTO внизу (як у грі на скриншоті)
	local auto = UIKit.Create("TextButton", {
		Name = "Auto",
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -12),
		Size = UDim2.fromOffset(100, 100),
		BackgroundColor3 = Color3.fromRGB(16, 22, 48),
		AutoButtonColor = true,
		Font = UIKit.Font,
		TextSize = 26,
		TextColor3 = Color3.new(1, 1, 1),
		Text = "🔄\nAUTO",
		ZIndex = 6,
		Parent = overlay,
	})
	UIKit.Create("UICorner", { CornerRadius = UDim.new(1, 0), Parent = auto })
	UIKit.Stroke(auto, Color3.fromRGB(70, 110, 220), 4)
	UIKit.TextOutline(auto, 2.5)
	UIKit.AddScale(auto)
	auto.Activated:Connect(function()
		if ui.toggleAuto then
			ui.toggleAuto()
		end
	end)

	local hint = UIKit.Label({
		AnchorPoint = Vector2.new(0, 1),
		Position = UDim2.new(0, 16, 1, -14),
		Size = UDim2.fromOffset(300, 30),
		TextXAlignment = Enum.TextXAlignment.Left,
		TextColor3 = UIKit.Colors.SubText,
		TextSize = 18,
		Text = "Натисни, щоб пропустити",
		ZIndex = 6,
		Parent = overlay,
	})

	ui.overlay = {
		root = overlay,
		flash = flash,
		rays = rays,
		rayParts = rayParts,
		glow = glow,
		holder = holder,
		pop = pop,
		viewport = viewport,
		camera = camera,
		model = nil,
		glints = glints,
		odds = odds,
		name = name,
		rarity = rarity,
		auto = auto,
		hint = hint,
	}

	-- Повільне обертання променів і героя
	game:GetService("RunService").RenderStepped:Connect(function(dt)
		if not overlay.Visible then
			return
		end
		rays.Rotation = (rays.Rotation + dt * 18) % 360
		local o = ui.overlay
		if o.model then
			o.model:PivotTo(CFrame.Angles(0, math.sin(os.clock() * 1.6) * 0.45, 0))
		end
	end)
end

local function oddsText(chance)
	local number = string.sub(GameMath.FormatOdds(chance), 6)
	return ('<font color="#FFFFFF">1 in </font><font color="#55B8FF">%s</font>'):format(number)
end

-- Показати героя у ViewportFrame
local function showHero(heroDef, awakened)
	local o = ui.overlay
	if o.model then
		o.model:Destroy()
		o.model = nil
	end
	local model = HeroModelBuilder.Build(heroDef, 1, "", awakened)
	local nameplate = model:FindFirstChild("Nameplate")
	if nameplate then
		nameplate:Destroy()
	end
	model.Parent = o.viewport
	o.model = model
	local s = heroDef.look.height or 1
	o.camera.CFrame = CFrame.lookAt(Vector3.new(0, 3.6 * s, -17 * s), Vector3.new(0, 3.4 * s, 0))
end

local function setDisplay(heroDef, chance)
	local o = ui.overlay
	local color = RarityConfig.GetColor(heroDef.rarity)
	showHero(heroDef, false)
	o.odds.Text = oddsText(chance)
	o.name.Text = heroDef.name
	o.rarity.Text = heroDef.rarity
	o.rarity.TextColor3 = color
	o.glow.BackgroundColor3 = color
	for _, ray in o.rayParts do
		ray.BackgroundColor3 = color:Lerp(Color3.new(1, 1, 1), 0.5)
	end
end

-- Випадковий герой для "прокрутки" (з тими ж вагами, що й справжній кидок)
local function randomHero(dice, luck)
	local weights, total = GameMath.GetRarityWeights(dice, luck)
	local roll = rng:NextNumber() * total
	local rarityName = "Common"
	for _, name in RarityConfig.Order do
		roll -= weights[name]
		if roll <= 0 and weights[name] > 0 then
			rarityName = name
			break
		end
	end
	local pool = HeroConfig.ByRarity[rarityName]
	return pool[rng:NextInteger(1, #pool)]
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
	local dice = DiceConfig.Dice[selectedDice] or DiceConfig.Dice.Basic
	local data = ClientState.Data
	local luck = if data then GameMath.GetLuck(data, workspace:GetServerTimeNow()) else 1
	skipRequested = false
	o.root.Visible = true
	o.rays.Visible = false
	for _, glint in o.glints do
		glint.Visible = false
	end

	-- 1. Прокрутка: герої змінюються дедалі повільніше. Для Legendary+ — довше (інтрига).
	local rare = rarityInfo.rank >= 4
	local steps = if rare then 13 else 8
	local delay = 0.06
	for _ = 1, steps do
		if skipRequested then
			break
		end
		local candidate = randomHero(dice, luck)
		setDisplay(candidate, GameMath.GetHeroChance(dice, candidate.id, luck))
		o.pop.Scale = 1.08
		TweenService:Create(o.pop, TweenInfo.new(0.08), { Scale = 1 }):Play()
		task.wait(delay)
		delay *= 1.2
	end
	skipRequested = false

	-- 2. Справжній результат
	setDisplay(heroDef, GameMath.GetHeroChance(dice, heroDef.id, luck))
	o.pop.Scale = 0.45
	TweenService:Create(o.pop, TweenInfo.new(0.4, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1.1 }):Play()

	local badges = {}
	if result.isNew then
		table.insert(badges, "🆕 NEW!")
	end
	if result.pity then
		table.insert(badges, "🎯 Гарантія!")
	end
	if result.free then
		table.insert(badges, "🎁 FREE")
	end
	-- Позначки в тому ж рядку, що й рідкість, золотим кольором
	if #badges > 0 then
		o.rarity.Text = heroDef.rarity .. '   <font color="#FFCD3C">' .. table.concat(badges, "   ") .. "</font>"
	end

	if effects then
		o.rays.Visible = rarityInfo.rank >= 2
		for side, glint in o.glints do
			glint.Visible = true
			glint.Position = UDim2.new(0.5, side * 460, 0.4, 0)
			TweenService:Create(glint, TweenInfo.new(0.35, Enum.EasingStyle.Quart), { Position = UDim2.new(0.5, side * 300, 0.4, 0) }):Play()
		end
		if rare then
			o.flash.BackgroundTransparency = 0.1
			TweenService:Create(o.flash, TweenInfo.new(0.7), { BackgroundTransparency = 1 }):Play()
		end
	end

	waitOrSkip(if autoRolling then 1.0 else 2.5)
	o.root.Visible = false
	if o.model then
		o.model:Destroy()
		o.model = nil
	end
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
		UIKit.SetOutline(button, if diceId == selectedDice then Color3.new(1, 1, 1) else UIKit.Colors.Outline, if diceId == selectedDice then 5 else 3)
	end

	local dice = DiceConfig.Dice[selectedDice]
	local free = data ~= nil and not data.tutorial.freeRollUsed and selectedDice == DiceConfig.TutorialDice
	local canAfford = free or (ClientState.Coins >= dice.price and isDiceUnlocked(data, dice))
	local priceText = if free then "🎁 FREE" else "🪙 " .. GameMath.FormatNumber(dice.price)
	if free then
		ui.rollButton.Text = "ROLL\n🎁 FREE!"
		ui.rollButton.BackgroundColor3 = UIKit.Colors.Success
	else
		ui.rollButton.Text = "ROLL\n" .. priceText
		ui.rollButton.BackgroundColor3 = if canAfford then UIKit.Colors.Accent else UIKit.Colors.Disabled
	end

	-- Велика кнопка ROLL і вибір кубика на головному екрані
	local bigRoll = Hud.Get("Roll")
	if bigRoll then
		bigRoll.Sub.Text = priceText
		bigRoll.Sub.TextColor3 = if canAfford then UIKit.Colors.Gold else UIKit.Colors.Danger
		bigRoll.Icon.Text = dice.icon
	end
	local dicePill = Hud.Get("Dice")
	if dicePill then
		dicePill.Text = ("%s %s ▾"):format(dice.icon, dice.displayName)
	end

	local autoUnlocked = data ~= nil and data.tutorial.completed
	if ui.overlay then
		ui.overlay.auto.BackgroundColor3 = if autoRolling then Color3.fromRGB(30, 140, 60) else Color3.fromRGB(16, 22, 48)
	end
	local autoButtons = { ui.autoButton, Hud.Get("Auto") }
	for _, button in autoButtons do
		if not autoUnlocked then
			button.Text = "🔒 AUTO"
			button.BackgroundColor3 = UIKit.Colors.Disabled
		else
			button.Text = if autoRolling then "AUTO: ON" else "AUTO: OFF"
			button.BackgroundColor3 = if autoRolling then UIKit.Colors.Success else UIKit.Colors.PanelLight
		end
	end

	-- Поточна удача (кубик × зілля × Rebirth)
	local luckLabel = Hud.Get("Luck")
	if luckLabel then
		local playerLuck = if data then GameMath.GetLuck(data, workspace:GetServerTimeNow()) else 1
		luckLabel.Text = "x" .. GameMath.FormatNumber(math.floor(dice.luck * playerLuck * 100 + 0.5) / 100)
	end

	local skip = ClientState.GetSetting("skipAnimations")
	ui.skipButton.Text = if skip then "⏩ Skip: ON" else "⏩ Skip: OFF"
	ui.skipButton.BackgroundColor3 = if skip then UIKit.Colors.Success else UIKit.Colors.PanelLight
end

local function toggleAuto()
	local data = ClientState.Data
	if not (data and data.tutorial.completed) then
		UIKit.Toast("Auto Roll відкриється після навчання: постав героя на базу", "info")
		return
	end
	setAuto(not autoRolling)
end

local function buildPanel(gui)
	local panel, content = UIKit.Panel(gui, "Roll", "🎲 Dice", Color3.fromRGB(190, 70, 255))
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
	ui.autoButton = UIKit.Button({ LayoutOrder = 2, Size = UDim2.fromOffset(130, 64), TextSize = 20 }, toggleAuto)
	ui.autoButton.Parent = buttons
	ui.skipButton = UIKit.Button({ LayoutOrder = 3, Size = UDim2.fromOffset(152, 64), TextSize = 19 }, function()
		ClientState.SetSetting("skipAnimations", not ClientState.GetSetting("skipAnimations"))
	end)
	ui.skipButton.Parent = buttons
end

function RollUI.Init(gui)
	buildPanel(gui)
	buildOverlay(gui)
	-- Велика кнопка ROLL одразу кидає вибраний кубик; AUTO вмикає автокидки
	Hud.SetAction("Roll", function()
		task.spawn(doRoll)
	end)
	Hud.SetAction("Auto", toggleAuto)
	ui.toggleAuto = toggleAuto
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
	-- Зілля удачі може закінчитись — оновлюємо шанси й удачу
	task.spawn(function()
		while true do
			task.wait(2)
			refreshButtons()
			if ui.panel and ui.panel.Visible then
				refreshInfo()
			end
		end
	end)
end

return RollUI
