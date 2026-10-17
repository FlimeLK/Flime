-- UpgradesUI: покращення бази за Coins і магазин за Crystals (зілля, більша сумка).

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))
local SoundController = require(Client:WaitForChild("SoundController"))

local UpgradesUI = {}

local rows = {}

-- Кожен рядок: currency ("Coins" | "Crystals"), describe(data, now), getPrice(data, now) -> ціна або nil (MAX), buy()
local ENTRIES = {
	{
		id = "Slots",
		title = "🧱 Слоти бази",
		currency = "Coins",
		describe = function(data)
			return ("Слотів: %d / %d. Більше героїв на базі — більше монет."):format(data.slotCount, EconomyConfig.MaxSlots)
		end,
		getPrice = function(data)
			return GameMath.GetSlotPrice(data.slotCount)
		end,
		remote = "BuyUpgrade",
	},
	{
		id = "Income",
		title = "💰 Дохід бази",
		currency = "Coins",
		describe = function(data)
			return ("Рівень %d. Множник доходу: ×%.1f (+%d%% за рівень)."):format(
				data.incomeLevel,
				GameMath.GetIncomeMultiplier(data.incomeLevel),
				EconomyConfig.IncomeUpgrade.bonusPerLevel * 100
			)
		end,
		getPrice = function(data)
			return GameMath.GetIncomeUpgradePrice(data.incomeLevel)
		end,
		remote = "BuyUpgrade",
	},
}

for _, itemId in ShopConfig.Order do
	local item = ShopConfig.Items[itemId]
	table.insert(ENTRIES, {
		id = itemId,
		title = item.displayName,
		currency = "Crystals",
		describe = function(data, now)
			if item.kind == "boost" then
				local left = (data.boosts[item.boost] or 0) - now
				if left > 0 then
					return item.description .. " • діє ще " .. GameMath.FormatTime(left)
				end
				return item.description
			end
			return ("%s • зараз %d місць"):format(item.description, GameMath.GetMaxInventory(data))
		end,
		getPrice = function(data)
			if item.kind == "inventory" then
				return GameMath.GetBagPrice(data)
			end
			return item.price
		end,
		remote = "BuyShopItem",
	})
end

local function refresh()
	local data = ClientState.Data
	if not data then
		return
	end
	local now = workspace:GetServerTimeNow()
	local affordableUpgrades = 0
	for _, entry in ENTRIES do
		local row = rows[entry.id]
		row.description.Text = entry.describe(data, now)
		local price = entry.getPrice(data, now)
		if price then
			local icon = if entry.currency == "Crystals" then "💎" else "🪙"
			local balance = if entry.currency == "Crystals" then ClientState.Crystals else ClientState.Coins
			row.button.Text = ("%s %s"):format(icon, GameMath.FormatNumber(price))
			row.button.BackgroundColor3 = if balance >= price
				then (if entry.currency == "Crystals" then UIKit.Colors.Accent2 else UIKit.Colors.Success)
				else UIKit.Colors.Disabled
			if entry.currency == "Coins" and balance >= price then
				affordableUpgrades += 1
			end
		else
			row.button.Text = "MAX"
			row.button.BackgroundColor3 = UIKit.Colors.Disabled
		end
	end
	-- Лічильник на кнопці UPGRADES: скільки покращень можна купити просто зараз
	Hud.SetBadge("Upgrades", affordableUpgrades)
end

-- Колір рамки картки для кожного товару
local CARD_COLORS = {
	Slots = Color3.fromRGB(70, 140, 255),
	Income = Color3.fromRGB(255, 185, 40),
	LuckPotion = Color3.fromRGB(70, 210, 90),
	CoinPotion = Color3.fromRGB(255, 185, 40),
	BigBag = Color3.fromRGB(170, 90, 255),
}

-- Картка товару: велика іконка, кольорова назва, опис і зелена кнопка ціни
local function buildCard(grid, order, entry)
	local color = CARD_COLORS[entry.id] or UIKit.Colors.Accent2
	local card = UIKit.Card({ LayoutOrder = order, Parent = grid }, color)

	local icon, name = string.match(entry.title, "^(%S+)%s+(.+)$")
	local iconLabel = UIKit.Icon({
		Key = entry.id, -- Slots, Income, LuckPotion, CoinPotion, BigBag
		Emoji = icon,
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 8),
		Size = UDim2.fromOffset(100, 84),
		Parent = card,
	})
	-- Іконка м'яко "плаває"
	TweenService:Create(iconLabel, TweenInfo.new(1.2, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), {
		Position = UDim2.new(0.5, 0, 0, 2),
	}):Play()

	local title = UIKit.Label({
		Position = UDim2.fromOffset(8, 92),
		Size = UDim2.new(1, -16, 0, 34),
		Font = UIKit.Font,
		TextScaled = true,
		TextColor3 = color:Lerp(Color3.new(1, 1, 1), 0.25),
		Text = name or entry.title,
		Outline = 3,
		Parent = card,
	})
	UIKit.Create("UITextSizeConstraint", { MaxTextSize = 30, Parent = title })
	local description = UIKit.Label({
		Position = UDim2.fromOffset(10, 126),
		Size = UDim2.new(1, -20, 0, 52),
		Font = UIKit.Font,
		TextScaled = true,
		Outline = 1.5,
		Parent = card,
	})
	UIKit.Create("UITextSizeConstraint", { MaxTextSize = 17, Parent = description })
	local button = UIKit.Button({
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -10),
		Size = UDim2.new(1, -30, 0, 48),
		BackgroundColor3 = UIKit.Colors.Success,
		TextSize = 28,
		Parent = card,
	}, function()
		local result = ClientState.Request(entry.remote, entry.id)
		if result.ok then
			SoundController.Play("Purchase")
		end
		UIKit.Toast(result.message or "", if result.ok then "info" else "error")
	end)
	button.TextOutline.Thickness = 3
	rows[entry.id] = { description = description, button = button }
end

-- Вікно з сіткою карток однієї валюти
local function buildPanel(gui, panelName, title, color, currency, sectionTitle, hint)
	local newPanel, content = UIKit.Panel(gui, panelName, title, color)
	Hud.RegisterPanel(panelName, newPanel)
	local list = UIKit.Create("ScrollingFrame", {
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		ScrollBarThickness = 8,
		CanvasSize = UDim2.new(),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Parent = content,
	})
	UIKit.Create("UIListLayout", {
		Padding = UDim.new(0, 8),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = list,
	})
	UIKit.Divider(list, sectionTitle, 1)
	UIKit.Label({
		LayoutOrder = 2,
		Size = UDim2.new(1, -12, 0, 22),
		TextSize = 15,
		TextColor3 = UIKit.Colors.SubText,
		Text = hint,
		Parent = list,
	})
	local grid = UIKit.Create("Frame", {
		LayoutOrder = 3,
		Size = UDim2.new(1, -12, 0, 0),
		AutomaticSize = Enum.AutomaticSize.Y,
		BackgroundTransparency = 1,
		Parent = list,
	})
	UIKit.Create("UIGridLayout", {
		CellSize = UDim2.fromOffset(230, 240),
		CellPadding = UDim2.fromOffset(12, 12),
		HorizontalAlignment = Enum.HorizontalAlignment.Center,
		SortOrder = Enum.SortOrder.LayoutOrder,
		Parent = grid,
	})
	UIKit.Create("UIPadding", { PaddingTop = UDim.new(0, 6), PaddingBottom = UDim.new(0, 6), Parent = grid })
	for index, entry in ENTRIES do
		if entry.currency == currency then
			buildCard(grid, index, entry)
		end
	end
	return newPanel
end

function UpgradesUI.Init(gui)
	local upgradesPanel = buildPanel(gui, "Upgrades", "⬆️ Upgrades", Color3.fromRGB(70, 205, 100), "Coins", "Base", "Покращення бази за 🪙 Coins")
	local shopPanel = buildPanel(gui, "Shop", "🛒 Shop", UIKit.Rainbow, "Crystals", "Crystal Shop", "💎 Кристали дають боси, завдання, колекція та Rebirth")

	ClientState.OnDataChanged(refresh)
	ClientState.OnCurrencyChanged(refresh)
	-- Таймери зілля
	task.spawn(function()
		while true do
			task.wait(1)
			if upgradesPanel.Visible or shopPanel.Visible then
				refresh()
			end
		end
	end)
end

return UpgradesUI
