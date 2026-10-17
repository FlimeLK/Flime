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
	Hud.SetBadge("Quests", countClaimable(data) > 0)
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
	local panel, content = UIKit.Panel(gui, "Quests", "📜 Quests")
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
