-- AdminUI: 👑 адмін-панель (лише для адмінів) + оголошення й таймер подій (для всіх).
--
-- Кнопка 👑 з'являється в верхньому меню, якщо сервер позначив гравця атрибутом IsAdmin.
-- На ПК панель також відкривається клавішею F2. Усі дії виконує й перевіряє сервер (AdminService).

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local AdminConfig = require(Config:WaitForChild("AdminConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local WorldConfig = require(Config:WaitForChild("WorldConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))
local Remotes = require(Shared:WaitForChild("Remotes"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))
local SoundController = require(Client:WaitForChild("SoundController"))

local player = Players.LocalPlayer

local AdminUI = {}

local GOLD = ColorSequence.new({
	ColorSequenceKeypoint.new(0, Color3.fromRGB(255, 220, 90)),
	ColorSequenceKeypoint.new(0.5, Color3.fromRGB(255, 140, 50)),
	ColorSequenceKeypoint.new(1, Color3.fromRGB(255, 70, 150)),
})
local COLORS = {
	Gold = Color3.fromRGB(255, 190, 50),
	Currency = Color3.fromRGB(255, 185, 40),
	Heroes = Color3.fromRGB(170, 90, 255),
	Progress = Color3.fromRGB(60, 200, 110),
	Player = Color3.fromRGB(60, 160, 255),
	Server = Color3.fromRGB(255, 80, 170),
	Log = Color3.fromRGB(120, 115, 160),
	Danger = Color3.fromRGB(235, 50, 65),
	Input = Color3.fromRGB(20, 18, 30),
}

local ui: { [string]: any } = {}
local selected = player -- гравець, над яким виконуються дії
local pages = {}
local tabButtons = {}

---------------------------------------------------------------------
-- Дрібні будівельні блоки
---------------------------------------------------------------------

-- "1.5m" → 1500000, "-250k" → -250000
local SUFFIX = { k = 1e3, m = 1e6, b = 1e9, t = 1e12 }
local function parseAmount(text)
	text = string.lower(string.gsub(text or "", "[%s,_]", ""))
	local number, suffix = string.match(text, "^(%-?[%d%.]+)(%a?)$")
	number = tonumber(number)
	if not number then
		return nil
	end
	if suffix ~= "" then
		if not SUFFIX[suffix] then
			return nil
		end
		number *= SUFFIX[suffix]
	end
	return math.floor(number)
end

local function input(parent, placeholder, props)
	local box = UIKit.Create("TextBox", {
		Size = UDim2.new(1, 0, 0, 44),
		BackgroundColor3 = COLORS.Input,
		Font = UIKit.BodyFont,
		TextSize = 18,
		TextColor3 = UIKit.Colors.Text,
		PlaceholderText = placeholder,
		PlaceholderColor3 = Color3.fromRGB(140, 130, 175),
		TextXAlignment = Enum.TextXAlignment.Left,
		ClearTextOnFocus = false,
		Text = "",
		Parent = parent,
	})
	for key, value in props or {} do
		box[key] = value
	end
	UIKit.Corner(box, 10)
	local stroke = UIKit.Stroke(box, Color3.fromRGB(110, 95, 170), 2)
	UIKit.Create("UIPadding", { PaddingLeft = UDim.new(0, 12), PaddingRight = UDim.new(0, 12), Parent = box })
	box.Focused:Connect(function()
		stroke.Color = COLORS.Gold
	end)
	box.FocusLost:Connect(function()
		stroke.Color = Color3.fromRGB(110, 95, 170)
	end)
	return box
end

local function button(parent, text, color, onClick, props)
	local b = UIKit.Button({
		Size = UDim2.fromOffset(150, 46),
		BackgroundColor3 = color,
		Text = text,
		TextSize = 18,
		Parent = parent,
	}, onClick)
	for key, value in props or {} do
		b[key] = value
	end
	return b
end

-- Кнопка небезпечної дії: перше натискання просить підтвердження
local function confirmButton(parent, text, onConfirm, props)
	local armedUntil = 0
	local b
	b = button(parent, text, COLORS.Danger, function()
		if os.clock() > armedUntil then
			armedUntil = os.clock() + 3
			b.Text = "⚠️ Точно? Ще раз!"
			task.delay(3.05, function()
				if os.clock() > armedUntil then
					b.Text = text
				end
			end)
			return
		end
		armedUntil = 0
		b.Text = text
		onConfirm()
	end, props)
	return b
end

-- Вибір одного з варіантів (чіпи). Повертає функцію, що віддає поточне значення.
local function chips(parent, options, default, color, width)
	local current = default
	local buttons = {}
	local function paint()
		for value, b in buttons do
			local active = value == current
			b.BackgroundColor3 = if active then color else Color3.fromRGB(70, 66, 92)
			UIKit.SetOutline(b, if active then Color3.new(1, 1, 1) else UIKit.Colors.Outline, 3)
		end
	end
	for index, option in options do
		local b = button(parent, option.text, color, function()
			current = option.value
			paint()
		end, { Size = UDim2.fromOffset(width or 72, 40), LayoutOrder = index })
		buttons[option.value] = b
	end
	paint()
	return function()
		return current
	end
end

-- Розділ сторінки: заголовок і тіло з вертикальним списком
local function section(page, title, color, order)
	local card = UIKit.Create("Frame", {
		Size = UDim2.new(1, -10, 0, 0),
		AutomaticSize = Enum.AutomaticSize.Y,
		BackgroundColor3 = Color3.fromRGB(28, 26, 38),
		LayoutOrder = order,
		Parent = page,
	})
	UIKit.Corner(card, 14)
	UIKit.Stroke(card, color, 3)
	local glow = UIKit.Create("Frame", {
		Size = UDim2.new(1, 0, 0, 44),
		BackgroundColor3 = color,
		BackgroundTransparency = 0.55,
		BorderSizePixel = 0,
		Parent = card,
	})
	UIKit.Corner(glow, 14)
	UIKit.Create("UIGradient", { Transparency = NumberSequence.new(0.2, 1), Parent = glow })
	UIKit.Create("UIPadding", {
		PaddingTop = UDim.new(0, 8),
		PaddingBottom = UDim.new(0, 12),
		PaddingLeft = UDim.new(0, 12),
		PaddingRight = UDim.new(0, 12),
		Parent = card,
	})
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = card })
	UIKit.Label({
		Size = UDim2.new(1, 0, 0, 30),
		Font = UIKit.Font,
		TextSize = 24,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = title,
		LayoutOrder = 0,
		Parent = card,
	})
	return card
end

-- Рядок кнопок, що переноситься
local function row(parent, order, height)
	local frame = UIKit.Create("Frame", {
		Size = UDim2.new(1, 0, 0, height or 0),
		AutomaticSize = if height then Enum.AutomaticSize.None else Enum.AutomaticSize.Y,
		BackgroundTransparency = 1,
		LayoutOrder = order or 1,
		Parent = parent,
	})
	UIKit.Create("UIListLayout", {
		FillDirection = Enum.FillDirection.Horizontal,
		Wraps = true,
		Padding = UDim.new(0, 8),
		VerticalAlignment = Enum.VerticalAlignment.Center,
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = frame,
	})
	return frame
end

-- fixed = true — сторінка без прокрутки (у неї своя прокрутна область)
local function newPage(name, fixed)
	local page = if fixed
		then UIKit.Create("Frame", { Name = name, Size = UDim2.fromScale(1, 1), BackgroundTransparency = 1, Visible = false, Parent = ui.pageHolder })
		else UIKit.Create("ScrollingFrame", {
			Name = name,
			Size = UDim2.fromScale(1, 1),
			BackgroundTransparency = 1,
			BorderSizePixel = 0,
			ScrollBarThickness = 6,
			ScrollBarImageColor3 = COLORS.Gold,
			CanvasSize = UDim2.new(),
			AutomaticCanvasSize = Enum.AutomaticSize.Y,
			Visible = false,
			Parent = ui.pageHolder,
		})
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 12), SortOrder = Enum.SortOrder.LayoutOrder, Parent = page })
	UIKit.Create("UIPadding", { PaddingTop = UDim.new(0, 4), PaddingLeft = UDim.new(0, 4), PaddingBottom = UDim.new(0, 8), Parent = page })
	pages[name] = page
	return page
end

---------------------------------------------------------------------
-- Запити до сервера
---------------------------------------------------------------------

local refreshTarget

local function request(action, args, perPlayer)
	args = args or {}
	if perPlayer then
		if not selected or selected.Parent == nil then
			selected = player
		end
		args.target = selected.UserId
	end
	local result = ClientState.Request("AdminAction", action, args)
	if result.message and result.message ~= "" then
		UIKit.Toast((if result.ok then "👑 " else "") .. result.message, if result.ok then "success" else "error")
	end
	if perPlayer then
		task.delay(0.25, refreshTarget)
	end
	return result
end

---------------------------------------------------------------------
-- Картка вибраного гравця
---------------------------------------------------------------------

local function playerList()
	local list = Players:GetPlayers()
	table.sort(list, function(a, b)
		if a == player or b == player then
			return a == player
		end
		return string.lower(a.Name) < string.lower(b.Name)
	end)
	return list
end

function refreshTarget()
	if not ui.targetName then
		return
	end
	if not selected or selected.Parent == nil then
		selected = player
	end
	local target = selected
	ui.targetName.Text = target.DisplayName
	ui.targetUser.Text = "@" .. target.Name .. (if target == player then " (ти)" else "")
	ui.avatar.Image = ""
	task.spawn(function()
		local ok, image = pcall(function()
			return Players:GetUserThumbnailAsync(target.UserId, Enum.ThumbnailType.HeadShot, Enum.ThumbnailSize.Size150x150)
		end)
		if ok and selected == target then
			ui.avatar.Image = image
		end
	end)
	local count = #Players:GetPlayers()
	ui.playerCount.Text = ("%d / %d"):format(table.find(playerList(), target) or 1, count)
	ui.stats.Text = "Завантаження…"
	task.spawn(function()
		local result = ClientState.Request("AdminAction", "Inspect", { target = target.UserId })
		if selected ~= target then
			return
		end
		if not result.ok then
			ui.stats.Text = result.message or "Немає даних"
			return
		end
		local world = WorldConfig.Worlds[result.world]
		ui.stats.Text = ("🪙 %s  •  💎 %s\n⚡ +%s/s\n♻️ Rebirth %d\n🦸 %d героїв • 📖 %d\n🎲 %s кидків\n🌍 %s"):format(
			GameMath.FormatNumber(result.coins),
			GameMath.FormatNumber(result.crystals),
			GameMath.FormatNumber(result.income),
			result.rebirths,
			result.heroes,
			result.discovered,
			GameMath.FormatNumber(result.totalRolls),
			if world then world.displayName else "Лобі"
		)
		ui.adminBadge.Visible = result.isAdmin == true
	end)
end

local function cycleTarget(step)
	local list = playerList()
	local index = table.find(list, selected) or 1
	selected = list[(index - 1 + step) % #list + 1]
	refreshTarget()
end

local function buildSidebar(content)
	local sidebar = UIKit.Create("Frame", {
		Size = UDim2.new(0, 220, 1, 0),
		BackgroundTransparency = 1,
		Parent = content,
	})

	-- Картка гравця
	local card = UIKit.Card({ Size = UDim2.new(1, 0, 0, 236), Parent = sidebar }, COLORS.Gold)
	local avatarFrame = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(10, 10),
		Size = UDim2.fromOffset(64, 64),
		BackgroundColor3 = Color3.fromRGB(60, 50, 90),
		Parent = card,
	})
	UIKit.Corner(avatarFrame, 32)
	UIKit.Stroke(avatarFrame, COLORS.Gold, 3)
	ui.avatar = UIKit.Create("ImageLabel", { Size = UDim2.fromScale(1, 1), BackgroundTransparency = 1, Parent = avatarFrame })
	UIKit.Corner(ui.avatar, 32)
	ui.adminBadge = UIKit.Label({
		Position = UDim2.fromOffset(44, 46),
		Size = UDim2.fromOffset(28, 28),
		Text = "👑",
		TextScaled = true,
		Visible = false,
		Parent = card,
	})
	ui.targetName = UIKit.Label({
		Position = UDim2.fromOffset(82, 12),
		Size = UDim2.new(1, -90, 0, 30),
		Font = UIKit.Font,
		TextScaled = true,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = card,
	})
	ui.targetUser = UIKit.Label({
		Position = UDim2.fromOffset(82, 42),
		Size = UDim2.new(1, -90, 0, 20),
		TextSize = 14,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextTruncate = Enum.TextTruncate.AtEnd,
		Parent = card,
	})
	ui.stats = UIKit.Label({
		Position = UDim2.fromOffset(12, 82),
		Size = UDim2.new(1, -24, 0, 104),
		TextSize = 14,
		LineHeight = 1.05,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextYAlignment = Enum.TextYAlignment.Top,
		Parent = card,
	})
	-- ◀ 1/3 ▶ та "Я"
	local nav = UIKit.Create("Frame", { Position = UDim2.new(0, 10, 1, -44), Size = UDim2.new(1, -20, 0, 36), BackgroundTransparency = 1, Parent = card })
	button(nav, "◀", COLORS.Player, function()
		cycleTarget(-1)
	end, { Size = UDim2.fromOffset(44, 36) })
	ui.playerCount = UIKit.Label({ Position = UDim2.fromOffset(48, 0), Size = UDim2.new(1, -150, 1, 0), Font = UIKit.Font, TextSize = 18, Parent = nav })
	button(nav, "▶", COLORS.Player, function()
		cycleTarget(1)
	end, { Size = UDim2.fromOffset(44, 36), Position = UDim2.new(1, -98, 0, 0) })
	button(nav, "Я", COLORS.Gold, function()
		selected = player
		refreshTarget()
	end, { Size = UDim2.fromOffset(46, 36), Position = UDim2.new(1, -46, 0, 0) })

	-- Вкладки
	local tabs = UIKit.Create("Frame", { Position = UDim2.fromOffset(0, 248), Size = UDim2.new(1, 0, 1, -248), BackgroundTransparency = 1, Parent = sidebar })
	UIKit.Create("UIGridLayout", { CellSize = UDim2.new(0.5, -4, 0, 42), CellPadding = UDim2.fromOffset(8, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = tabs })
	for index, tab in {
		{ "Currency", "💰 Валюта" },
		{ "Heroes", "🦸 Герої" },
		{ "Progress", "🗺️ Прогрес" },
		{ "Player", "🧍 Гравець" },
		{ "Server", "📢 Сервер" },
		{ "Log", "📜 Журнал" },
	} do
		local id = tab[1]
		tabButtons[id] = button(tabs, tab[2], COLORS[id], function()
			AdminUI.ShowTab(id)
		end, { LayoutOrder = index, TextSize = 15 })
	end
end

function AdminUI.ShowTab(id)
	for name, page in pages do
		page.Visible = name == id
	end
	for name, b in tabButtons do
		local active = name == id
		b.BackgroundColor3 = if active then COLORS[name] else COLORS[name]:Lerp(Color3.fromRGB(40, 38, 55), 0.6)
		UIKit.SetOutline(b, if active then Color3.new(1, 1, 1) else UIKit.Colors.Outline, 3)
	end
	if id == "Log" then
		AdminUI.RefreshLog()
	end
end

---------------------------------------------------------------------
-- Сторінки
---------------------------------------------------------------------

local function buildCurrency()
	local page = newPage("Currency")
	for order, kind in { { "Coins", "🪙 Монети", { 1e3, 1e5, 1e7, 1e9 } }, { "Crystals", "💎 Кристали", { 10, 100, 1000, 10000 } } } do
		local card = section(page, kind[2], COLORS.Currency, order)
		local quick = row(card, 1)
		for index, amount in kind[3] do
			button(quick, "+" .. GameMath.FormatNumber(amount), if kind[1] == "Coins" then Color3.fromRGB(240, 170, 30) else Color3.fromRGB(70, 180, 255), function()
				request(kind[1], { amount = amount }, true)
			end, { LayoutOrder = index, Size = UDim2.fromOffset(120, 44) })
		end
		local custom = row(card, 2, 44)
		local box = input(custom, "Своя кількість: 2500, 1.5m, 3b…", { Size = UDim2.new(1, -236, 0, 44) })
		local function send(sign)
			local amount = parseAmount(box.Text)
			if not amount or amount <= 0 then
				UIKit.Toast("Введи число, напр. 5000 або 2.5m", "error")
				return
			end
			request(kind[1], { amount = amount * sign }, true)
		end
		button(custom, "➕ Видати", UIKit.Colors.Success, function()
			send(1)
		end, { Size = UDim2.fromOffset(110, 44), LayoutOrder = 2 })
		button(custom, "➖ Забрати", COLORS.Danger, function()
			send(-1)
		end, { Size = UDim2.fromOffset(110, 44), LayoutOrder = 3 })
	end

	local boosts = section(page, "🧪 Бусти", Color3.fromRGB(90, 220, 120), 3)
	local boostRow = row(boosts, 1)
	for index, entry in {
		{ "luck", 15, "🍀 Удача 15 хв" },
		{ "luck", 60, "🍀 Удача 1 год" },
		{ "income", 15, "💰 Дохід 15 хв" },
		{ "income", 60, "💰 Дохід 1 год" },
	} do
		button(boostRow, entry[3], if entry[1] == "luck" then Color3.fromRGB(70, 200, 90) else Color3.fromRGB(240, 170, 30), function()
			request("Boost", { boost = entry[1], minutes = entry[2] }, true)
		end, { LayoutOrder = index, Size = UDim2.fromOffset(145, 44), TextSize = 15 })
	end
end

local function buildHeroes()
	local page = newPage("Heroes", true)
	local selectedHero = nil
	local cards = {}

	local top = UIKit.Create("Frame", { Size = UDim2.new(1, -10, 0, 44), BackgroundTransparency = 1, LayoutOrder = 1, Parent = page })
	local search = input(top, "🔍 Пошук: ім'я, рідкість або стихія…", { Size = UDim2.fromScale(1, 1) })

	local grid = UIKit.Create("ScrollingFrame", {
		Size = UDim2.new(1, -10, 1, -158),
		BackgroundColor3 = Color3.fromRGB(24, 22, 34),
		BorderSizePixel = 0,
		ScrollBarThickness = 6,
		ScrollBarImageColor3 = COLORS.Heroes,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		LayoutOrder = 2,
		Parent = page,
	})
	UIKit.Corner(grid, 12)
	UIKit.Stroke(grid, COLORS.Heroes, 3)
	UIKit.Create("UIPadding", { PaddingTop = UDim.new(0, 8), PaddingLeft = UDim.new(0, 8), PaddingRight = UDim.new(0, 8), PaddingBottom = UDim.new(0, 8), Parent = grid })
	UIKit.Create("UIGridLayout", { CellSize = UDim2.fromOffset(142, 62), CellPadding = UDim2.fromOffset(8, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = grid })

	local controls = UIKit.Card({ Size = UDim2.new(1, -10, 0, 86), LayoutOrder = 3, Parent = page }, COLORS.Heroes)
	local chosen = UIKit.Label({
		Position = UDim2.fromOffset(12, 6),
		Size = UDim2.new(1, -24, 0, 24),
		Font = UIKit.Font,
		TextSize = 20,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "Обери героя зі списку",
		Parent = controls,
	})
	local line = row(controls, 1, 44)
	line.Position = UDim2.fromOffset(12, 34)
	line.Size = UDim2.new(1, -24, 0, 44)
	local level = input(line, "Рівень (макс.)", { Size = UDim2.fromOffset(130, 40), LayoutOrder = 1 })
	local awakened = false
	local awakenButton
	awakenButton = button(line, "✨ Пробуджений: ні", Color3.fromRGB(70, 66, 92), function()
		awakened = not awakened
		awakenButton.Text = if awakened then "✨ Пробуджений: так" else "✨ Пробуджений: ні"
		awakenButton.BackgroundColor3 = if awakened then COLORS.Gold else Color3.fromRGB(70, 66, 92)
	end, { Size = UDim2.fromOffset(170, 40), LayoutOrder = 2, TextSize = 14 })
	local countHolder = UIKit.Create("Frame", { Size = UDim2.fromOffset(156, 40), BackgroundTransparency = 1, LayoutOrder = 3, Parent = line })
	UIKit.Create("UIListLayout", { FillDirection = Enum.FillDirection.Horizontal, Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, Parent = countHolder })
	local getCount = chips(countHolder, { { text = "×1", value = 1 }, { text = "×5", value = 5 }, { text = "×10", value = 10 } }, 1, COLORS.Heroes, 48)
	button(line, "🎁 Видати", UIKit.Colors.Success, function()
		if not selectedHero then
			UIKit.Toast("Спершу обери героя", "error")
			return
		end
		request("GiveHero", { heroId = selectedHero, level = tonumber(level.Text), awakened = awakened, count = getCount() }, true)
	end, { Size = UDim2.fromOffset(124, 40), LayoutOrder = 4 })

	for index, heroDef in HeroConfig.List do
		local rarityColor = RarityConfig.GetColor(heroDef.rarity)
		local card = UIKit.Button({
			Name = heroDef.id,
			BackgroundColor3 = rarityColor:Lerp(Color3.fromRGB(20, 18, 30), 0.45),
			Text = "",
			LayoutOrder = RarityConfig.GetRank(heroDef.rarity) * 100 + index,
			Parent = grid,
		}, function()
			selectedHero = heroDef.id
			for id, other in cards do
				UIKit.SetOutline(other, if id == heroDef.id then COLORS.Gold else UIKit.Colors.Outline, if id == heroDef.id then 5 else 3)
			end
			local maxLevel = RarityConfig.Info[heroDef.rarity].maxLevel
			chosen.Text = ("%s %s • %s • макс. Lv %d"):format(HeroConfig.ElementIcons[heroDef.element] or "", heroDef.name, heroDef.rarity, maxLevel)
			chosen.TextColor3 = rarityColor
		end)
		UIKit.HeroPortrait(card, heroDef.id, 0.5)
		UIKit.Label({
			Position = UDim2.fromOffset(6, 4),
			Size = UDim2.new(1, -12, 0, 30),
			Font = UIKit.Font,
			TextScaled = true,
			Text = heroDef.name,
			Parent = card,
		})
		UIKit.Label({
			Position = UDim2.fromOffset(6, 36),
			Size = UDim2.new(1, -12, 0, 20),
			Font = UIKit.Font,
			TextScaled = true,
			TextColor3 = rarityColor:Lerp(Color3.new(1, 1, 1), 0.35),
			Text = (HeroConfig.ElementIcons[heroDef.element] or "") .. " " .. heroDef.rarity,
			Parent = card,
		})
		cards[heroDef.id] = card
	end

	search:GetPropertyChangedSignal("Text"):Connect(function()
		local query = string.lower(search.Text)
		for _, heroDef in HeroConfig.List do
			local text = string.lower(heroDef.name .. " " .. heroDef.rarity .. " " .. heroDef.element)
			cards[heroDef.id].Visible = query == "" or string.find(text, query, 1, true) ~= nil
		end
	end)
end

local function buildProgress()
	local page = newPage("Progress")
	local unlock = section(page, "🔓 Прогрес гравця", COLORS.Progress, 1)
	local unlockRow = row(unlock, 1)
	for index, entry in {
		{ "UnlockAll", "🌍 Відкрити все" },
		{ "MaxBase", "🧱 Макс. база" },
		{ "AddRebirth", "♻️ +1 Rebirth" },
	} do
		button(unlockRow, entry[2], COLORS.Progress, function()
			request(entry[1], {}, true)
		end, { LayoutOrder = index, Size = UDim2.fromOffset(170, 46) })
	end
	UIKit.Label({
		Size = UDim2.new(1, 0, 0, 20),
		TextSize = 14,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = "«Відкрити все» — світи, зони й кубики. «+1 Rebirth» — бонус без скидання прогресу.",
		LayoutOrder = 2,
		Parent = unlock,
	})

	local travel = section(page, "🌀 Телепорт у світ (без вимог)", Color3.fromRGB(70, 150, 255), 2)
	local travelRow = row(travel, 1)
	button(travelRow, "🏠 Лобі", Color3.fromRGB(255, 120, 200), function()
		request("Travel", { world = "Lobby" }, true)
	end, { LayoutOrder = 0, Size = UDim2.fromOffset(170, 46) })
	for index, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		if world.available then
			button(travelRow, world.displayName, world.color, function()
				request("Travel", { world = worldId }, true)
			end, { LayoutOrder = index, Size = UDim2.fromOffset(170, 46), TextSize = 16 })
		end
	end

	local danger = section(page, "⚠️ Небезпечна зона", COLORS.Danger, 3)
	local dangerRow = row(danger, 1)
	confirmButton(dangerRow, "🗑️ Скинути прогрес", function()
		request("ResetData", {}, true)
	end, { Size = UDim2.fromOffset(220, 46) })
end

local function buildPlayer()
	local page = newPage("Player")
	local move = section(page, "📍 Переміщення", COLORS.Player, 1)
	local moveRow = row(move, 1)
	for index, entry in { { "GoTo", "➡️ До гравця" }, { "Bring", "⬅️ До себе" }, { "Heal", "❤️ Вилікувати" } } do
		button(moveRow, entry[2], if entry[1] == "Heal" then UIKit.Colors.Success else COLORS.Player, function()
			request(entry[1], {}, true)
		end, { LayoutOrder = index, Size = UDim2.fromOffset(170, 46) })
	end

	local speed = section(page, "🏃 Швидкість ходьби", Color3.fromRGB(80, 220, 200), 2)
	local speedRow = row(speed, 1)
	for index, value in AdminConfig.WalkSpeeds do
		button(speedRow, (if index == 1 then "🚶 " else "🏃 ") .. value, Color3.fromRGB(50, 190, 170), function()
			request("Speed", { speed = value }, true)
		end, { LayoutOrder = index, Size = UDim2.fromOffset(120, 46) })
	end

	local kick = section(page, "🚪 Вигнати з сервера", COLORS.Danger, 3)
	local kickRow = row(kick, 1, 46)
	local reason = input(kickRow, "Причина (необов'язково)", { Size = UDim2.new(1, -168, 0, 46) })
	confirmButton(kickRow, "🚪 Вигнати", function()
		request("Kick", { reason = reason.Text }, true)
		reason.Text = ""
	end, { Size = UDim2.fromOffset(160, 46), LayoutOrder = 2 })
end

local function buildServer()
	local page = newPage("Server")
	local announce = section(page, "📢 Оголошення для всіх", COLORS.Server, 1)
	local announceRow = row(announce, 1, 46)
	local text = input(announceRow, "Напр.: Через 5 хвилин подія удачі ×3!", { Size = UDim2.new(1, -168, 0, 46) })
	button(announceRow, "📢 Надіслати", COLORS.Server, function()
		if #text.Text < 2 then
			UIKit.Toast("Напиши текст оголошення", "error")
			return
		end
		if request("Announce", { text = text.Text }).ok then
			text.Text = ""
		end
	end, { Size = UDim2.fromOffset(160, 46), LayoutOrder = 2 })

	local events = section(page, "🎉 Подія для всього сервера", COLORS.Gold, 2)
	local minutesRow = row(events, 1)
	UIKit.Label({ Size = UDim2.fromOffset(110, 40), Font = UIKit.Font, TextSize = 18, Text = "⏱ Тривалість:", LayoutOrder = 0, Parent = minutesRow })
	local getMinutes = chips(minutesRow, { { text = "5 хв", value = 5 }, { text = "15 хв", value = 15 }, { text = "30 хв", value = 30 }, { text = "60 хв", value = 60 } }, 15, COLORS.Gold, 76)
	for order, kind in { { "Luck", "🍀 Удача", Color3.fromRGB(70, 200, 90) }, { "Income", "💰 Дохід", Color3.fromRGB(240, 170, 30) } } do
		local eventRow = row(events, order + 1)
		UIKit.Label({ Size = UDim2.fromOffset(110, 44), Font = UIKit.Font, TextSize = 18, Text = kind[2], TextColor3 = kind[3], LayoutOrder = 0, Parent = eventRow })
		for index, multiplier in AdminConfig.EventMultipliers do
			button(eventRow, "×" .. multiplier, kind[3], function()
				request("Event", { kind = kind[1], multiplier = multiplier, minutes = getMinutes() })
			end, { LayoutOrder = index, Size = UDim2.fromOffset(76, 44) })
		end
	end
	local stopRow = row(events, 5)
	button(stopRow, "⏹ Зупинити всі події", COLORS.Danger, function()
		request("StopEvents")
	end, { Size = UDim2.fromOffset(240, 44) })

	local world = section(page, "⚔️ Світ", Color3.fromRGB(255, 110, 70), 3)
	local worldRow = row(world, 1)
	confirmButton(worldRow, "💥 Перемогти всіх ворогів тут", function()
		request("ClearWorld")
	end, { Size = UDim2.fromOffset(300, 46) })
end

local function buildLog()
	local page = newPage("Log")
	local head = row(page, 0, 44)
	button(head, "🔄 Оновити", COLORS.Log, function()
		AdminUI.RefreshLog()
	end, { Size = UDim2.fromOffset(150, 40) })
	ui.logList = UIKit.Create("Frame", { Size = UDim2.new(1, -10, 0, 0), AutomaticSize = Enum.AutomaticSize.Y, BackgroundTransparency = 1, LayoutOrder = 1, Parent = page })
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, Parent = ui.logList })
end

function AdminUI.RefreshLog()
	if not ui.logList then
		return
	end
	local result = ClientState.Request("AdminAction", "GetLog")
	for _, child in ui.logList:GetChildren() do
		if child:IsA("GuiObject") then
			child:Destroy()
		end
	end
	local entries = if result.ok and type(result.log) == "table" then result.log else {}
	if #entries == 0 then
		UIKit.Label({ Size = UDim2.new(1, 0, 0, 40), TextSize = 18, TextColor3 = UIKit.Colors.SubText, Text = "Поки що порожньо", Parent = ui.logList })
	end
	for index, entry in entries do
		local line = UIKit.Create("Frame", { Size = UDim2.new(1, 0, 0, 40), BackgroundColor3 = if index % 2 == 0 then Color3.fromRGB(32, 30, 44) else Color3.fromRGB(26, 24, 36), LayoutOrder = index, Parent = ui.logList })
		UIKit.Corner(line, 10)
		UIKit.Label({
			Position = UDim2.fromOffset(10, 0),
			Size = UDim2.new(1, -20, 1, 0),
			TextSize = 15,
			TextXAlignment = Enum.TextXAlignment.Left,
			RichText = true,
			TextTruncate = Enum.TextTruncate.AtEnd,
			Text = ('<font color="#a8a0d0">%s</font>  <b>%s</b> → <font color="#ffcc55">%s</font>%s %s'):format(
				os.date("%H:%M:%S", entry.time),
				entry.admin or "?",
				entry.action or "?",
				if entry.target then " • " .. entry.target else "",
				entry.details or ""
			),
			Parent = line,
		})
	end
end

---------------------------------------------------------------------
-- Панель і кнопка 👑
---------------------------------------------------------------------

local function buildPanel(gui)
	local panel, content = UIKit.Panel(gui, "Admin", "👑 Admin Panel", GOLD)
	panel.Size = UDim2.fromOffset(920, 580)
	Hud.RegisterPanel("Admin", panel)
	ui.panel = panel

	buildSidebar(content)
	ui.pageHolder = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(236, 0),
		Size = UDim2.new(1, -236, 1, 0),
		BackgroundTransparency = 1,
		Parent = content,
	})
	buildCurrency()
	buildHeroes()
	buildProgress()
	buildPlayer()
	buildServer()
	buildLog()
	AdminUI.ShowTab("Currency")

	panel:GetPropertyChangedSignal("Visible"):Connect(function()
		if panel.Visible then
			refreshTarget()
		end
	end)
	Players.PlayerAdded:Connect(function()
		if panel.Visible then
			refreshTarget()
		end
	end)
	Players.PlayerRemoving:Connect(function(leaving)
		if leaving == selected then
			selected = player
		end
		task.defer(function()
			if panel.Visible then
				refreshTarget()
			end
		end)
	end)

	-- Кнопка 👑 у верхньому меню поруч із Worlds / Home / Shop
	local topNav = Hud.Get("Worlds") and Hud.Get("Worlds").Parent
	local crown = UIKit.Button({
		Name = "Admin",
		LayoutOrder = 10,
		Size = UDim2.fromOffset(62, 62),
		BackgroundColor3 = COLORS.Gold,
		Text = "👑",
		TextScaled = true,
		Parent = topNav or gui,
	}, function()
		Hud.TogglePanel("Admin")
	end)
	crown.Outline.UIStroke.Thickness = 4
	if not topNav then
		crown.Position = UDim2.new(0, 12, 0, 70)
		UIKit.AddScale(crown)
	end

	UserInputService.InputBegan:Connect(function(inputObject, gameProcessed)
		if not gameProcessed and inputObject.KeyCode == Enum.KeyCode.F2 then
			Hud.TogglePanel("Admin")
		end
	end)
end

---------------------------------------------------------------------
-- Для всіх гравців: оголошення та таймер подій
---------------------------------------------------------------------

local function buildAnnouncements(gui)
	local holder = UIKit.Create("Frame", {
		Name = "Announcement",
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 150),
		Size = UDim2.fromOffset(640, 100),
		BackgroundColor3 = Color3.fromRGB(26, 20, 40),
		Visible = false,
		ZIndex = 60,
		Parent = gui,
	})
	UIKit.Corner(holder, 20)
	local stroke = UIKit.Stroke(holder, Color3.new(1, 1, 1), 5)
	local rainbow = UIKit.Create("UIGradient", { Color = UIKit.Rainbow, Parent = stroke })
	UIKit.Create("UIGradient", { Color = ColorSequence.new(Color3.fromRGB(255, 255, 255), Color3.fromRGB(170, 160, 200)), Rotation = 90, Parent = holder })
	local scale = UIKit.AddScale(holder)
	local title = UIKit.Label({
		Position = UDim2.fromOffset(16, 8),
		Size = UDim2.new(1, -32, 0, 26),
		Font = UIKit.Font,
		TextSize = 22,
		TextColor3 = COLORS.Gold,
		Text = "📢 ОГОЛОШЕННЯ",
		ZIndex = 61,
		Parent = holder,
	})
	local body = UIKit.Label({
		Position = UDim2.fromOffset(16, 36),
		Size = UDim2.new(1, -32, 1, -44),
		Font = UIKit.Font,
		TextScaled = true,
		ZIndex = 61,
		Parent = holder,
	})
	UIKit.Create("UITextSizeConstraint", { MaxTextSize = 30, Parent = body })

	local token = 0
	Remotes.Get("Announce").OnClientEvent:Connect(function(text, author)
		token += 1
		local mine = token
		title.Text = "📢 ОГОЛОШЕННЯ" .. (if typeof(author) == "string" then " від " .. author else "")
		body.Text = tostring(text)
		holder.Visible = true
		holder.Size = UDim2.fromOffset(640, 100)
		local base = scale.Scale
		scale.Scale = base * 0.6
		TweenService:Create(scale, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = base }):Play()
		SoundController.Play("Reward")
		task.spawn(function()
			while holder.Visible and token == mine do
				rainbow.Rotation = (rainbow.Rotation + 4) % 360
				task.wait(0.03)
			end
		end)
		task.delay(7, function()
			if token == mine then
				holder.Visible = false
			end
		end)
	end)
end

local function buildEventTimer(gui)
	local pill = UIKit.Create("Frame", {
		Name = "ServerEvents",
		AnchorPoint = Vector2.new(1, 0),
		Position = UDim2.new(1, -12, 0, 164),
		Size = UDim2.fromOffset(230, 0),
		AutomaticSize = Enum.AutomaticSize.Y,
		BackgroundTransparency = 1,
		Visible = false,
		Parent = gui,
	})
	UIKit.AddScale(pill)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 6), HorizontalAlignment = Enum.HorizontalAlignment.Right, SortOrder = Enum.SortOrder.LayoutOrder, Parent = pill })
	local labels = {}
	for index, kind in { { "Luck", "🍀 Удача", Color3.fromRGB(70, 200, 90) }, { "Income", "💰 Дохід", Color3.fromRGB(240, 170, 30) } } do
		local label = UIKit.Label({
			Size = UDim2.fromOffset(230, 40),
			BackgroundColor3 = kind[3],
			BackgroundTransparency = 0,
			Font = UIKit.Font,
			TextSize = 20,
			LayoutOrder = index,
			Visible = false,
			Parent = pill,
		})
		UIKit.Corner(label, 12)
		UIKit.Stroke(label, UIKit.Colors.Outline, 3)
		UIKit.Shade(label, 0.25)
		labels[kind[1]] = { label = label, name = kind[2] }
	end
	task.spawn(function()
		while true do
			local now = workspace:GetServerTimeNow()
			local any = false
			for kind, entry in labels do
				local multiplier = GameMath.GetEventMultiplier(kind, now)
				local ends = workspace:GetAttribute("Event" .. kind .. "Ends")
				local active = multiplier > 1 and type(ends) == "number"
				entry.label.Visible = active
				if active then
					any = true
					entry.label.Text = ("🎉 %s ×%d • %s"):format(entry.name, multiplier, GameMath.FormatTime(math.max(0, ends - now)))
				end
			end
			pill.Visible = any
			task.wait(1)
		end
	end)
end

function AdminUI.Init(gui)
	buildAnnouncements(gui)
	buildEventTimer(gui)
	-- Панель будуємо лише для адмінів (сервер ставить атрибут; він може прийти трохи пізніше)
	local built = false
	local function check()
		if not built and player:GetAttribute("IsAdmin") == true then
			built = true
			buildPanel(gui)
		end
	end
	player:GetAttributeChangedSignal("IsAdmin"):Connect(check)
	check()
end

return AdminUI
