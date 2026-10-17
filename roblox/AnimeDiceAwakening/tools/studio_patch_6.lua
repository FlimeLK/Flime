-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.
-- Частина 6 з 7. Запускай усі частини по черзі: від 1 до 7.
-- Studio → зупини гру (Stop) → View → Command Bar → встав увесь текст → ▶ Run.
-- Замінює код скриптів нижче на нову версію. Ctrl+Z скасовує зміни.
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local recording = ChangeHistoryService:TryBeginRecording("AnimeDiceAwakening patch")

local function setSource(path, className, source)
	local parent = game:GetService(path[1])
	for i = 2, #path - 1 do
		local child = parent:FindFirstChild(path[i])
		if not child then
			child = Instance.new("Folder")
			child.Name = path[i]
			child.Parent = parent
		end
		parent = child
	end
	local target = parent:FindFirstChild(path[#path])
	if target and not target:IsA(className) then
		warn("❌ " .. target:GetFullName() .. " — не " .. className .. ", пропускаю")
		return
	end
	if not target then
		target = Instance.new(className)
		target.Name = path[#path]
		target.Parent = parent
	end
	-- Через ScriptEditorService, щоб оновились і відкриті вкладки редактора
	local ok = pcall(function()
		ScriptEditorService:UpdateSourceAsync(target, function()
			return source
		end)
	end)
	if not ok then
		target.Source = source
	end
	print("✅ оновлено " .. target:GetFullName())
end

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "QuestsUI" }, "ModuleScript", [=[
-- QuestsUI: вікно Quests з вкладками "Завдання" (сюжет + щоденні) і "Колекція"
-- (усі герої, бонус доходу, нагороди за відкриття). Нагороди видає сервер.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local QuestConfig = require(Config:WaitForChild("QuestConfig"))
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local QuestsUI = {}

local ui: { [string]: any } = {}
local activeTab = "Quests"
local busy = false

local function serverNow()
	return workspace:GetServerTimeNow()
end

local function request(action, arg)
	if busy then
		return
	end
	busy = true
	local result = ClientState.Request("QuestAction", action, arg)
	busy = false
	UIKit.Toast(result.message or "", if result.ok then "success" else "error")
end

-- Щоденний прогрес з урахуванням нового дня (поки сервер ще не обнулив)
local function dailyState(data)
	local today = GameMath.GetDay(serverNow())
	if data.daily.day ~= today then
		return today, {}, {}
	end
	return today, data.daily.progress, data.daily.claimed
end

---------------------------------------------------------------------
-- Картка завдання
---------------------------------------------------------------------

local function makeQuestCard(parent, order, height)
	local card = UIKit.Create("Frame", {
		LayoutOrder = order,
		Size = UDim2.new(1, -12, 0, height),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.25,
		Parent = parent,
	})
	UIKit.Corner(card, 12)
	local stroke = UIKit.Stroke(card, UIKit.Colors.PanelLight, 2)
	local title = UIKit.Label({
		Position = UDim2.fromOffset(12, 4),
		Size = UDim2.new(1, -200, 0, 26),
		Font = UIKit.Font,
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = card,
	})
	local description = UIKit.Label({
		Position = UDim2.fromOffset(12, 30),
		Size = UDim2.new(1, -200, 0, 20),
		TextSize = 14,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextTruncate = Enum.TextTruncate.AtEnd,
		Parent = card,
	})
	local back = UIKit.Create("Frame", {
		Position = UDim2.new(0, 12, 1, -24),
		Size = UDim2.new(1, -200, 0, 16),
		BackgroundColor3 = Color3.fromRGB(30, 25, 50),
		Parent = card,
	})
	UIKit.Corner(back, 6)
	local fill = UIKit.Create("Frame", { Size = UDim2.fromScale(0, 1), BackgroundColor3 = UIKit.Colors.Accent2, Parent = back })
	UIKit.Corner(fill, 6)
	local progress = UIKit.Label({ Size = UDim2.fromScale(1, 1), TextSize = 12, TextStrokeTransparency = 0.4, Parent = back })
	local reward = UIKit.Label({
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -12, 0, 4),
		Size = UDim2.fromOffset(170, 24),
		Font = UIKit.Font,
		TextSize = 17,
		TextColor3 = UIKit.Colors.Gold,
		Parent = card,
	})
	local button = UIKit.Button({
		AnchorPoint = Vector2.new(1, 1),
		Position = UDim2.new(1, -12, 1, -6),
		Size = UDim2.fromOffset(170, 34),
		TextSize = 18,
		Parent = card,
	})
	return { card = card, stroke = stroke, title = title, description = description, fill = fill, progress = progress, reward = reward, button = button }
end

-- state: "claim" | "progress" | "done"
local function fillCard(refs, title, description, current, target, reward, state)
	refs.title.Text = title
	refs.description.Text = description
	refs.fill.Size = UDim2.fromScale(math.clamp(current / math.max(target, 1), 0, 1), 1)
	refs.progress.Text = GameMath.FormatNumber(math.min(current, target)) .. " / " .. GameMath.FormatNumber(target)
	refs.reward.Text = GameMath.FormatReward(reward)
	if state == "claim" then
		refs.button.Text = "🎁 Claim"
		refs.button.BackgroundColor3 = UIKit.Colors.Success
		refs.stroke.Color = UIKit.Colors.Success
	elseif state == "done" then
		refs.button.Text = "✅ Отримано"
		refs.button.BackgroundColor3 = UIKit.Colors.Disabled
		refs.stroke.Color = UIKit.Colors.PanelLight
	else
		refs.button.Text = "У процесі"
		refs.button.BackgroundColor3 = UIKit.Colors.Disabled
		refs.stroke.Color = UIKit.Colors.PanelLight
	end
end

---------------------------------------------------------------------
-- Підрахунок доступних нагород (для червоної позначки на кнопці Quests)
---------------------------------------------------------------------

local function countClaimable(data)
	local count = 0
	local main = QuestConfig.Main[data.quests.main]
	if main and GameMath.GetMetric(data, main.metric) >= main.target then
		count += 1
	end
	local today, progress, claimed = dailyState(data)
	for _, quest in QuestConfig.GetDaily(today) do
		if not claimed[quest.id] and (progress[quest.event] or 0) >= quest.target then
			count += 1
		end
	end
	local discovered = GameMath.CountDiscovered(data)
	for index, milestone in QuestConfig.CollectionMilestones do
		if not data.collectionClaimed["m" .. index] and discovered >= milestone.count then
			count += 1
		end
	end
	return count
end

---------------------------------------------------------------------
-- Вкладка "Завдання"
---------------------------------------------------------------------

local function refreshQuests(data)
	local mainQuest = QuestConfig.Main[data.quests.main]
	if mainQuest then
		local current = GameMath.GetMetric(data, mainQuest.metric)
		fillCard(ui.main, ("%d. %s"):format(data.quests.main, mainQuest.title), mainQuest.description, current, mainQuest.target, mainQuest.reward, if current >= mainQuest.target then "claim" else "progress")
	else
		fillCard(ui.main, "🏆 Сюжет пройдено!", "Нові завдання з'являться разом з новими світами", 1, 1, {}, "done")
	end

	local today, progress, claimed = dailyState(data)
	for index, quest in QuestConfig.GetDaily(today) do
		local refs = ui.daily[index]
		local current = progress[quest.event] or 0
		local state = if claimed[quest.id] then "done" elseif current >= quest.target then "claim" else "progress"
		fillCard(refs, quest.title, quest.description, current, quest.target, quest.reward, state)
		refs.questId = quest.id
	end
end

local function refreshTimer()
	local now = serverNow()
	local nextDay = (GameMath.GetDay(now) + 1) * 86400
	ui.dailyHeader.Text = "📅 Щоденні завдання • нові через " .. GameMath.FormatTime(nextDay - now)
end

---------------------------------------------------------------------
-- Вкладка "Колекція"
---------------------------------------------------------------------

local function refreshCollection(data)
	local discovered = GameMath.CountDiscovered(data)
	ui.collectionHeader.Text = ("📖 Відкрито %d / %d • бонус доходу бази +%d%%"):format(
		discovered,
		#HeroConfig.List,
		math.floor(discovered * EconomyConfig.CollectionIncomeBonus * 100 + 0.5)
	)
	for index, milestone in QuestConfig.CollectionMilestones do
		local button = ui.milestones[index]
		local claimed = data.collectionClaimed["m" .. index]
		local ready = discovered >= milestone.count
		button.Text = ("%s %d героїв\n+%d 💎"):format(if claimed then "✅" elseif ready then "🎁" else "🔒", milestone.count, milestone.crystals)
		button.BackgroundColor3 = if claimed then UIKit.Colors.Disabled elseif ready then UIKit.Colors.Success else UIKit.Colors.PanelLight
	end

	for _, child in ui.collectionGrid:GetChildren() do
		if child:IsA("Frame") then
			child:Destroy()
		end
	end
	for order, heroDef in HeroConfig.List do
		local known = data.discovered[heroDef.id] == true
		local color = RarityConfig.GetColor(heroDef.rarity)
		local cell = UIKit.Create("Frame", {
			LayoutOrder = order,
			BackgroundColor3 = if known then color:Lerp(UIKit.Colors.Background, 0.6) else Color3.fromRGB(25, 22, 35),
			Parent = ui.collectionGrid,
		})
		UIKit.Corner(cell, 10)
		-- Невідомий герой — темний силует портрета
		local portrait = UIKit.HeroPortrait(cell, heroDef.id, if known then 0.35 else 0.85)
		if portrait and not known then
			portrait.ImageColor3 = Color3.new(0, 0, 0)
		end
		UIKit.Stroke(cell, if known then color else UIKit.Colors.Disabled, 2)
		UIKit.Label({
			Position = UDim2.fromOffset(4, 4),
			Size = UDim2.new(1, -8, 0, 40),
			Font = UIKit.Font,
			TextSize = 15,
			TextColor3 = if known then color else UIKit.Colors.Disabled,
			Text = if known then heroDef.name else "???",
			Parent = cell,
		})
		UIKit.Label({
			Position = UDim2.fromOffset(4, 46),
			Size = UDim2.new(1, -8, 0, 22),
			TextSize = 13,
			TextColor3 = color,
			Text = (if known then (HeroConfig.ElementIcons[heroDef.element] or "") .. " " else "") .. heroDef.rarity,
			Parent = cell,
		})
	end
end

---------------------------------------------------------------------

local function refresh()
	local data = ClientState.Data
	if not data then
		return
	end
	Hud.SetBadge("Quests", countClaimable(data))
	if not ui.panel.Visible then
		return
	end
	if activeTab == "Quests" then
		refreshQuests(data)
		refreshTimer()
	else
		refreshCollection(data)
	end
end

local function selectTab(name)
	activeTab = name
	ui.questsBody.Visible = name == "Quests"
	ui.collectionBody.Visible = name == "Collection"
	ui.tabQuests.BackgroundColor3 = if name == "Quests" then UIKit.Colors.Accent else UIKit.Colors.PanelLight
	ui.tabCollection.BackgroundColor3 = if name == "Collection" then UIKit.Colors.Accent else UIKit.Colors.PanelLight
	refresh()
end

local function buildQuestsBody(content)
	local body = UIKit.Create("ScrollingFrame", {
		Position = UDim2.fromOffset(0, 52),
		Size = UDim2.new(1, 0, 1, -52),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		ScrollBarThickness = 8,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Parent = content,
	})
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = body })
	ui.questsBody = body

	UIKit.Label({
		LayoutOrder = 1,
		Size = UDim2.new(1, -12, 0, 26),
		Font = UIKit.Font,
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "📖 Сюжет",
		Parent = body,
	})
	ui.main = makeQuestCard(body, 2, 92)
	ui.main.button.Activated:Connect(function()
		request("ClaimMain")
	end)

	ui.dailyHeader = UIKit.Label({
		LayoutOrder = 3,
		Size = UDim2.new(1, -12, 0, 26),
		Font = UIKit.Font,
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = body,
	})
	ui.daily = {}
	for index = 1, QuestConfig.DailyCount do
		local refs = makeQuestCard(body, 3 + index, 86)
		refs.button.Activated:Connect(function()
			if refs.questId then
				request("ClaimDaily", refs.questId)
			end
		end)
		ui.daily[index] = refs
	end
end

local function buildCollectionBody(content)
	local body = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(0, 52),
		Size = UDim2.new(1, 0, 1, -52),
		BackgroundTransparency = 1,
		Visible = false,
		Parent = content,
	})
	ui.collectionBody = body
	ui.collectionHeader = UIKit.Label({
		Size = UDim2.new(1, 0, 0, 28),
		Font = UIKit.Font,
		TextSize = 19,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = body,
	})
	local row = UIKit.Create("Frame", { Position = UDim2.fromOffset(0, 32), Size = UDim2.new(1, 0, 0, 52), BackgroundTransparency = 1, Parent = body })
	UIKit.Create("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = row })
	ui.milestones = {}
	local count = #QuestConfig.CollectionMilestones
	for index = 1, count do
		ui.milestones[index] = UIKit.Button({
			LayoutOrder = index,
			Size = UDim2.new(1 / count, -6, 1, 0),
			TextSize = 16,
			Parent = row,
		}, function()
			request("ClaimCollection", index)
		end)
	end

	ui.collectionGrid = UIKit.Create("ScrollingFrame", {
		Position = UDim2.fromOffset(0, 92),
		Size = UDim2.new(1, 0, 1, -92),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.4,
		BorderSizePixel = 0,
		ScrollBarThickness = 8,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Parent = body,
	})
	UIKit.Corner(ui.collectionGrid, 12)
	UIKit.Create("UIGridLayout", {
		CellSize = UDim2.fromOffset(112, 74),
		CellPadding = UDim2.fromOffset(8, 8),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = ui.collectionGrid,
	})
	UIKit.Create("UIPadding", {
		PaddingTop = UDim.new(0, 8),
		PaddingLeft = UDim.new(0, 8),
		PaddingRight = UDim.new(0, 8),
		PaddingBottom = UDim.new(0, 8),
		Parent = ui.collectionGrid,
	})
end

function QuestsUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Quests", "📜 Quests", Color3.fromRGB(255, 150, 40))
	ui.panel = panel
	Hud.RegisterPanel("Quests", panel)

	ui.tabQuests = UIKit.Button({
		Size = UDim2.fromOffset(200, 44),
		Text = "📜 Завдання",
		Parent = content,
	}, function()
		selectTab("Quests")
	end)
	ui.tabCollection = UIKit.Button({
		Position = UDim2.fromOffset(210, 0),
		Size = UDim2.fromOffset(200, 44),
		Text = "📖 Колекція",
		Parent = content,
	}, function()
		selectTab("Collection")
	end)

	buildQuestsBody(content)
	buildCollectionBody(content)
	selectTab("Quests")

	-- 📜 Quests і 📖 Index відкривають одне вікно на різних вкладках
	local function openTab(tab)
		if panel.Visible and activeTab == tab then
			panel.Visible = false
		else
			Hud.OpenPanel("Quests")
			selectTab(tab)
		end
	end
	Hud.SetAction("Quests", function()
		openTab("Quests")
	end)
	Hud.SetAction("Index", function()
		openTab("Collection")
	end)

	panel:GetPropertyChangedSignal("Visible"):Connect(refresh)
	ClientState.OnDataChanged(refresh)

	-- Таймер щоденних завдань і зміна дня
	task.spawn(function()
		local lastDay = nil
		while true do
			task.wait(1)
			local day = GameMath.GetDay(serverNow())
			if day ~= lastDay then
				lastDay = day
				refresh()
			elseif panel.Visible and activeTab == "Quests" then
				refreshTimer()
			end
		end
	end)
end

return QuestsUI
]=])

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "RollUI" }, "ModuleScript", [=[
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
local HeroArtConfig = require(Config:WaitForChild("HeroArtConfig"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))
local SoundController = require(Client:WaitForChild("SoundController"))

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
	local portrait = UIKit.Create("ImageLabel", {
		Name = "Portrait",
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		ScaleType = Enum.ScaleType.Fit,
		Visible = false,
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
		Text = "AUTO",
		TextYAlignment = Enum.TextYAlignment.Bottom,
		ZIndex = 6,
		Parent = overlay,
	})
	UIKit.Create("UIPadding", { PaddingBottom = UDim.new(0, 12), Parent = auto })
	UIKit.Icon({
		Key = "Auto",
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 10),
		Size = UDim2.fromScale(0.56, 0.56),
		ZIndex = 7,
		Parent = auto,
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
		portrait = portrait,
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
	-- Якщо для героя підключено свій портрет — показуємо його замість 3D-моделі
	local portrait = HeroArtConfig.GetPortrait(heroDef.id, true)
	o.portrait.Visible = portrait ~= nil
	o.viewport.Visible = portrait == nil
	if portrait then
		o.portrait.Image = portrait
		return
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
		SoundController.Play("RollTick", 0.9 + rng:NextNumber() * 0.3)
		o.pop.Scale = 1.08
		TweenService:Create(o.pop, TweenInfo.new(0.08), { Scale = 1 }):Play()
		task.wait(delay)
		delay *= 1.2
	end
	skipRequested = false

	-- 2. Справжній результат
	setDisplay(heroDef, GameMath.GetHeroChance(dice, heroDef.id, luck))
	SoundController.Play(if rare then "RareReveal" else "Reveal")
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
		UIKit.SetIconEmoji(bigRoll.Icon, dice.icon)
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
			Size = UDim2.new(1, 0, 0, 50), -- 7 кубиків мають вміститися у вікно
			TextSize = 16,
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
]=])

setSource({ "StarterPlayer", "StarterPlayerScripts", "Client", "TeamUI" }, "ModuleScript", [=[
-- TeamUI: вікно бойової команди. Зверху 3 слоти, нижче — усі герої за шкодою.
-- Дотик по герою: додати в команду / прибрати. Герой з бази переходить у команду сам.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local TeamUI = {}

local ui: { [string]: any } = {}
local dirty = true
local busy = false

local function request(action, uid)
	if busy then
		return
	end
	busy = true
	local result = ClientState.Request("TeamAction", action, uid)
	busy = false
	UIKit.Toast(result.message or "", if result.ok then "success" else "error")
end

local function heroLine(heroDef, hero)
	return ("Lv %d • ⚔️ %s/s"):format(hero.level, GameMath.FormatNumber(math.floor(GameMath.GetHeroDps(heroDef, hero.level, hero.awakened))))
end

local function refreshSlots(data)
	for slot = 1, CombatConfig.TeamSize do
		local card = ui.slots[slot]
		local uid = data.team[slot]
		local hero = uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			local color = RarityConfig.GetColor(heroDef.rarity)
			card.BackgroundColor3 = color:Lerp(UIKit.Colors.Background, 0.55)
			card.Stroke.Color = color
			card.Title.Text = heroDef.name
			card.Title.TextColor3 = color
			card.Info.Text = heroLine(heroDef, hero) .. "\n✦ " .. heroDef.ability.name .. "   (натисни, щоб прибрати)"
		else
			card.BackgroundColor3 = UIKit.Colors.Background
			card.Stroke.Color = UIKit.Colors.Disabled
			card.Title.Text = ("Слот %d"):format(slot)
			card.Title.TextColor3 = UIKit.Colors.SubText
			card.Info.Text = "Порожньо — вибери героя нижче"
		end
	end
	ui.dps.Text = "⚔️ Шкода команди: " .. GameMath.FormatNumber(math.floor(GameMath.GetTeamDps(data))) .. "/s"
end

local function refreshGrid(data)
	for _, child in ui.grid:GetChildren() do
		if child:IsA("GuiButton") then
			child:Destroy()
		end
	end
	local list = {}
	for uid, hero in data.heroes do
		local heroDef = HeroConfig.Heroes[hero.id]
		if heroDef then
			table.insert(list, { uid = uid, hero = hero, def = heroDef, dps = GameMath.GetHeroDps(heroDef, hero.level, hero.awakened) })
		end
	end
	table.sort(list, function(a, b)
		if a.dps ~= b.dps then
			return a.dps > b.dps
		end
		return a.uid < b.uid
	end)
	for order, entry in list do
		local inTeam = GameMath.IsInTeam(data, entry.uid)
		local onBase = GameMath.IsOnBase(data, entry.uid)
		local color = RarityConfig.GetColor(entry.def.rarity)
		local card = UIKit.Create("TextButton", {
			Name = entry.uid,
			LayoutOrder = order,
			BackgroundColor3 = color:Lerp(UIKit.Colors.Background, if inTeam then 0.3 else 0.6),
			Text = "",
			Parent = ui.grid,
		})
		UIKit.Corner(card, 10)
		UIKit.HeroPortrait(card, entry.def.id)
		UIKit.Stroke(card, if inTeam then Color3.new(1, 1, 1) else color, if inTeam then 3 else 2)
		UIKit.Label({
			Position = UDim2.fromOffset(4, 4),
			Size = UDim2.new(1, -8, 0, 38),
			Font = UIKit.Font,
			TextSize = 15,
			TextColor3 = color,
			Text = entry.def.name,
			Parent = card,
		})
		UIKit.Label({
			Position = UDim2.fromOffset(4, 44),
			Size = UDim2.new(1, -8, 0, 20),
			TextSize = 13,
			Text = heroLine(entry.def, entry.hero),
			Parent = card,
		})
		UIKit.Label({
			Position = UDim2.fromOffset(4, 66),
			Size = UDim2.new(1, -8, 0, 22),
			TextSize = 15,
			Text = (HeroConfig.ElementIcons[entry.def.element] or "") .. (if inTeam then " ⚔️ у команді" elseif onBase then " 🏠 на базі" else ""),
			Parent = card,
		})
		card.Activated:Connect(function()
			request(if inTeam then "Remove" else "Add", entry.uid)
		end)
	end
end

local function refresh()
	local data = ClientState.Data
	if not data then
		return
	end
	if not ui.panel.Visible then
		dirty = true
		return
	end
	dirty = false
	refreshSlots(data)
	refreshGrid(data)
end

function TeamUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Team", "⚔️ Team", Color3.fromRGB(255, 120, 60))
	ui.panel = panel
	Hud.RegisterPanel("Team", panel)
	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		if panel.Visible and dirty then
			refresh()
		end
	end)

	-- 3 слоти команди
	local slotsRow = UIKit.Create("Frame", { Size = UDim2.new(1, 0, 0, 96), BackgroundTransparency = 1, Parent = content })
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		Padding = UDim.new(0, 10),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = slotsRow,
	})
	ui.slots = {}
	for slot = 1, CombatConfig.TeamSize do
		local card = UIKit.Create("TextButton", {
			LayoutOrder = slot,
			Size = UDim2.new(1 / CombatConfig.TeamSize, -7, 1, 0),
			BackgroundColor3 = UIKit.Colors.Background,
			Text = "",
			Parent = slotsRow,
		})
		UIKit.Corner(card, 12)
		UIKit.Stroke(card, UIKit.Colors.Disabled, 2).Name = "Stroke"
		UIKit.Label({
			Name = "Title",
			Position = UDim2.fromOffset(8, 4),
			Size = UDim2.new(1, -16, 0, 30),
			Font = UIKit.Font,
			TextSize = 19,
			Parent = card,
		})
		UIKit.Label({
			Name = "Info",
			Position = UDim2.fromOffset(8, 36),
			Size = UDim2.new(1, -16, 1, -40),
			TextSize = 13,
			TextColor3 = UIKit.Colors.SubText,
			Parent = card,
		})
		card.Activated:Connect(function()
			local data = ClientState.Data
			local uid = data and data.team[slot]
			if uid and uid ~= "" then
				request("Remove", uid)
			end
		end)
		ui.slots[slot] = card
	end

	-- Рядок керування
	ui.dps = UIKit.Label({
		Position = UDim2.fromOffset(0, 104),
		Size = UDim2.new(1, -330, 0, 40),
		Font = UIKit.Font,
		TextSize = 19,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = content,
	})
	UIKit.Button({
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -140, 0, 104),
		Size = UDim2.fromOffset(180, 40),
		BackgroundColor3 = UIKit.Colors.Success,
		TextSize = 18,
		Text = "⭐ Best Team",
		Parent = content,
	}, function()
		request("Best")
	end)
	UIKit.Button({
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, 0, 0, 104),
		Size = UDim2.fromOffset(130, 40),
		BackgroundColor3 = UIKit.Colors.PanelLight,
		TextSize = 18,
		Text = "✖ Clear",
		Parent = content,
	}, function()
		request("Clear")
	end)

	-- Усі герої
	ui.grid = UIKit.Create("ScrollingFrame", {
		Position = UDim2.fromOffset(0, 152),
		Size = UDim2.new(1, 0, 1, -152),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.4,
		BorderSizePixel = 0,
		ScrollBarThickness = 8,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Parent = content,
	})
	UIKit.Corner(ui.grid, 12)
	UIKit.Create("UIGridLayout", {
		CellSize = UDim2.fromOffset(112, 92),
		CellPadding = UDim2.fromOffset(8, 8),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = ui.grid,
	})
	UIKit.Create("UIPadding", {
		PaddingTop = UDim.new(0, 8),
		PaddingLeft = UDim.new(0, 8),
		PaddingRight = UDim.new(0, 8),
		PaddingBottom = UDim.new(0, 8),
		Parent = ui.grid,
	})

	ClientState.OnDataChanged(refresh)
end

return TeamUI
]=])

if recording then
	ChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)
end
print("Частина 6 з 7 готова")
