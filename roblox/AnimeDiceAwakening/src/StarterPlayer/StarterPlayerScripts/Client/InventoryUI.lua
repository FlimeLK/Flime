-- InventoryUI: сітка героїв, сортування, Equip Best і дії з вибраним героєм
-- (Place / Remove, Lock, Merge, Sell). Кожна дія — запит до сервера.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local InventoryUI = {}

local SORTS = {
	{ id = "rarity", label = "Рідкість" },
	{ id = "income", label = "Дохід" },
	{ id = "level", label = "Рівень" },
	{ id = "newest", label = "Нові" },
}

local sortIndex = 1
local selectedUid = nil
local busy = false
local dirty = true
local ui: { [string]: any } = {}

local function getPlacedSet(data)
	local placed = {}
	for i = 1, data.slotCount do
		local uid = data.slots[i]
		if uid ~= "" then
			placed[uid] = true
		end
	end
	return placed
end

local function getSortedHeroes(data)
	local mode = SORTS[sortIndex].id
	local list = {}
	for uid, hero in data.heroes do
		local heroDef = HeroConfig.Heroes[hero.id]
		if heroDef then
			table.insert(list, {
				uid = uid,
				hero = hero,
				def = heroDef,
				rank = RarityConfig.GetRank(heroDef.rarity),
				income = GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened),
				number = tonumber(string.sub(uid, 2)) or 0,
			})
		end
	end
	table.sort(list, function(a, b)
		if mode == "rarity" then
			if a.rank ~= b.rank then
				return a.rank > b.rank
			end
			if a.income ~= b.income then
				return a.income > b.income
			end
		elseif mode == "income" then
			if a.income ~= b.income then
				return a.income > b.income
			end
		elseif mode == "level" then
			if a.hero.level ~= b.hero.level then
				return a.hero.level > b.hero.level
			end
		end
		return a.number > b.number -- новіші вище
	end)
	return list
end

local function countDuplicates(data, uid, heroId)
	local count = 0
	local placed = getPlacedSet(data)
	for otherUid, other in data.heroes do
		if otherUid ~= uid and other.id == heroId and not other.locked and not placed[otherUid] and not GameMath.IsInTeam(data, otherUid) then
			count += 1
		end
	end
	return count
end

local refreshAll -- оголошена нижче

local function request(action, uid)
	if busy then
		return
	end
	busy = true
	local result = ClientState.Request("InventoryAction", action, uid)
	busy = false
	UIKit.Toast(result.message or "", if result.ok then "success" else "error")
	if result.ok and action == "Sell" then
		selectedUid = nil
	end
end

local function makeCard(entry, placed, order)
	local color = RarityConfig.GetColor(entry.def.rarity)
	local card = UIKit.Create("TextButton", {
		Name = entry.uid,
		LayoutOrder = order,
		BackgroundColor3 = color:Lerp(UIKit.Colors.Background, 0.6),
		AutoButtonColor = true,
		Text = "",
		Parent = ui.grid,
	})
	UIKit.Corner(card, 12)
	UIKit.Shade(card, 0.3)
	local selected = entry.uid == selectedUid
	UIKit.Stroke(card, if selected then Color3.new(1, 1, 1) elseif entry.hero.awakened then UIKit.Colors.Gold else color, if selected then 4 else 3)

	UIKit.Label({
		Position = UDim2.fromOffset(4, 4),
		Size = UDim2.new(1, -8, 0, 38),
		Font = UIKit.Font,
		TextSize = 15,
		TextColor3 = if entry.hero.awakened then UIKit.Colors.Gold else color,
		Text = (if entry.hero.awakened then "✨" else "") .. GameMath.GetHeroName(entry.def, entry.hero.awakened),
		Parent = card,
	})
	UIKit.Label({
		Position = UDim2.fromOffset(4, 44),
		Size = UDim2.new(1, -8, 0, 20),
		TextSize = 14,
		Text = ("Lv %d • +%s/s"):format(entry.hero.level, GameMath.FormatNumber(entry.income)),
		Parent = card,
	})
	local icons = (HeroConfig.ElementIcons[entry.def.element] or "")
		.. (if placed[entry.uid] then " 🏠" else "")
		.. (if GameMath.IsInTeam(ClientState.Data, entry.uid) then " ⚔️" else "")
		.. (if entry.hero.locked then " 🔒" else "")
	UIKit.Label({
		Position = UDim2.fromOffset(4, 66),
		Size = UDim2.new(1, -8, 0, 22),
		TextSize = 16,
		Text = icons,
		Parent = card,
	})

	card.Activated:Connect(function()
		selectedUid = entry.uid
		refreshAll()
	end)
end

local function refreshDetails(data, placed)
	local hero = selectedUid and data.heroes[selectedUid]
	local heroDef = hero and HeroConfig.Heroes[hero.id]
	ui.details.Visible = heroDef ~= nil
	ui.emptyDetails.Visible = heroDef == nil
	if not heroDef then
		selectedUid = nil
		return
	end
	local rarityInfo = RarityConfig.Info[heroDef.rarity]
	local isPlaced = placed[selectedUid] == true
	ui.detailText.Text = ("<font color=\"#%s\"><b>%s</b> (%s)</font>\n%s %s • %s • Lv %d/%d\n⚔️ %s  ⏱ %.1f/s  🪙 +%s/s\n✦ %s: %s"):format(
		(if hero.awakened then UIKit.Colors.Gold else rarityInfo.color):ToHex(),
		(if hero.awakened then "✨ " else "") .. GameMath.GetHeroName(heroDef, hero.awakened),
		heroDef.rarity,
		HeroConfig.ElementIcons[heroDef.element] or "",
		heroDef.element,
		heroDef.archetype,
		hero.level,
		rarityInfo.maxLevel,
		GameMath.FormatNumber(GameMath.GetHeroDamage(heroDef, hero.level, hero.awakened)),
		heroDef.attackSpeed,
		GameMath.FormatNumber(GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)),
		heroDef.ability.name,
		heroDef.ability.description
	)

	ui.placeButton.Text = if isPlaced then "🏠 Remove" else "🏠 Place"
	ui.placeButton.BackgroundColor3 = if isPlaced then UIKit.Colors.PanelLight else UIKit.Colors.Success
	ui.lockButton.Text = if hero.locked then "🔓 Unlock" else "🔒 Lock"
	local duplicates = countDuplicates(data, selectedUid, hero.id)
	ui.mergeButton.Text = ("⬆️ Merge (%d)"):format(duplicates)
	ui.mergeButton.BackgroundColor3 = if duplicates > 0 and hero.level < rarityInfo.maxLevel then UIKit.Colors.Accent else UIKit.Colors.Disabled
	local canSell = not hero.locked and not isPlaced and not GameMath.IsInTeam(data, selectedUid)
	ui.sellButton.Text = "💰 Sell " .. GameMath.FormatNumber(GameMath.GetSellPrice(heroDef, hero.level))
	ui.sellButton.BackgroundColor3 = if canSell then UIKit.Colors.Gold:Lerp(UIKit.Colors.Danger, 0.3) else UIKit.Colors.Disabled

	local canAwaken, _, cost = GameMath.CanAwaken(heroDef, hero)
	if hero.awakened then
		ui.awakenButton.Text = "✨ Пробуджено"
		ui.awakenButton.BackgroundColor3 = UIKit.Colors.Disabled
	else
		ui.awakenButton.Text = ("✨ Awaken %d💎"):format(cost)
		ui.awakenButton.BackgroundColor3 = if canAwaken and ClientState.Crystals >= cost then UIKit.Colors.Gold else UIKit.Colors.Disabled
	end
end

function refreshAll()
	local data = ClientState.Data
	if not data then
		return
	end
	if not ui.panel.Visible then
		dirty = true -- оновимо, коли вікно відкриють
		return
	end
	dirty = false

	for _, child in ui.grid:GetChildren() do
		if child:IsA("GuiButton") then
			child:Destroy()
		end
	end
	local placed = getPlacedSet(data)
	local list = getSortedHeroes(data)
	for order, entry in list do
		makeCard(entry, placed, order)
	end
	ui.countLabel.Text = ("Герої: %d / %d"):format(#list, GameMath.GetMaxInventory(data))
	ui.sortButton.Text = "↕ " .. SORTS[sortIndex].label
	refreshDetails(data, placed)
end

local function buildPanel(gui)
	local panel, content = UIKit.Panel(gui, "Inventory", "🎒 Backpack", Color3.fromRGB(135, 85, 255))
	ui.panel = panel
	Hud.RegisterPanel("Inventory", panel)
	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		if panel.Visible and dirty then
			refreshAll()
		end
	end)

	-- Верхній рядок
	ui.countLabel = UIKit.Label({
		Size = UDim2.fromOffset(240, 40),
		Font = UIKit.Font,
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = content,
	})
	ui.sortButton = UIKit.Button({
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -190, 0, 0),
		Size = UDim2.fromOffset(170, 40),
		BackgroundColor3 = UIKit.Colors.PanelLight,
		TextSize = 18,
		Parent = content,
	}, function()
		sortIndex = sortIndex % #SORTS + 1
		refreshAll()
	end)
	UIKit.Button({
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, 0, 0, 0),
		Size = UDim2.fromOffset(180, 40),
		BackgroundColor3 = UIKit.Colors.Success,
		TextSize = 18,
		Text = "⭐ Equip Best",
		Parent = content,
	}, function()
		request("EquipBest")
	end)

	-- Сітка героїв
	ui.grid = UIKit.Create("ScrollingFrame", {
		Position = UDim2.fromOffset(0, 48),
		Size = UDim2.new(1, 0, 1, -48 - 112),
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

	-- Нижня панель із деталями вибраного героя
	local bottom = UIKit.Create("Frame", {
		AnchorPoint = Vector2.new(0, 1),
		Position = UDim2.fromScale(0, 1),
		Size = UDim2.new(1, 0, 0, 104),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.3,
		Parent = content,
	})
	UIKit.Corner(bottom, 12)

	ui.emptyDetails = UIKit.Label({
		Size = UDim2.fromScale(1, 1),
		TextColor3 = UIKit.Colors.SubText,
		Text = "Вибери героя, щоб поставити його на базу, заблокувати, злити або продати",
		Parent = bottom,
	})

	ui.details = UIKit.Create("Frame", { Size = UDim2.fromScale(1, 1), BackgroundTransparency = 1, Parent = bottom })
	ui.detailText = UIKit.Label({
		Position = UDim2.fromOffset(10, 4),
		Size = UDim2.new(1, -456, 1, -8),
		TextSize = 14,
		RichText = true,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextYAlignment = Enum.TextYAlignment.Top,
		Parent = ui.details,
	})
	local actions = UIKit.Create("Frame", {
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -8, 0.5, 0),
		Size = UDim2.fromOffset(440, 92),
		BackgroundTransparency = 1,
		Parent = ui.details,
	})
	UIKit.Create("UIGridLayout", {
		CellSize = UDim2.fromOffset(140, 43),
		CellPadding = UDim2.fromOffset(8, 6),
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = actions,
	})
	local function actionButton(order, callback)
		local button = UIKit.Button({ LayoutOrder = order, TextSize = 17, Parent = actions }, callback)
		return button
	end
	ui.placeButton = actionButton(1, function()
		local data = ClientState.Data
		if data and selectedUid then
			request(if getPlacedSet(data)[selectedUid] then "Remove" else "Place", selectedUid)
		end
	end)
	ui.lockButton = actionButton(2, function()
		if selectedUid then
			request("Lock", selectedUid)
		end
	end)
	ui.lockButton.BackgroundColor3 = UIKit.Colors.PanelLight
	ui.mergeButton = actionButton(3, function()
		if selectedUid then
			request("Merge", selectedUid)
		end
	end)
	ui.sellButton = actionButton(4, function()
		if selectedUid then
			request("Sell", selectedUid)
		end
	end)
	-- Пробудження: герой максимального рівня + кристали
	ui.awakenButton = actionButton(5, function()
		if selectedUid then
			request("Awaken", selectedUid)
		end
	end)
end

function InventoryUI.Init(gui)
	buildPanel(gui)
	ClientState.OnDataChanged(function()
		refreshAll()
	end)
end

return InventoryUI
