-- UpgradesUI: покращення бази за Coins і магазин за Crystals (зілля, більша сумка).

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = Shared:WaitForChild("Config")
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

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

local function buildRow(list, order, entry)
	local row = UIKit.Create("Frame", {
		LayoutOrder = order,
		Size = UDim2.new(1, -12, 0, 88),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.2,
		Parent = list,
	})
	UIKit.Corner(row, 16)
	UIKit.Stroke(row, UIKit.Colors.Outline, 3)

	-- Квадратна іконка ліворуч (перший символ назви — емодзі)
	local icon, name = string.match(entry.title, "^(%S+)%s+(.+)$")
	local iconBox = UIKit.Label({
		Position = UDim2.fromOffset(10, 10),
		Size = UDim2.fromOffset(68, 68),
		BackgroundColor3 = if entry.currency == "Crystals" then UIKit.Colors.Accent2 else UIKit.Colors.Success,
		BackgroundTransparency = 0,
		TextScaled = true,
		Text = icon or "⭐",
		Outline = 0,
		Parent = row,
	})
	UIKit.Corner(iconBox, 14)
	UIKit.Stroke(iconBox, UIKit.Colors.Outline, 3)
	UIKit.Shade(iconBox, 0.3)

	UIKit.Label({
		Position = UDim2.fromOffset(92, 8),
		Size = UDim2.new(1, -300, 0, 34),
		Font = UIKit.Font,
		TextSize = 26,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = name or entry.title,
		Outline = 2.5,
		Parent = row,
	})
	local description = UIKit.Label({
		Position = UDim2.fromOffset(92, 44),
		Size = UDim2.new(1, -300, 0, 38),
		TextSize = 15,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = row,
	})
	local button = UIKit.Button({
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -14, 0.5, 0),
		Size = UDim2.fromOffset(190, 60),
		TextSize = 24,
		Parent = row,
	}, function()
		local result = ClientState.Request(entry.remote, entry.id)
		UIKit.Toast(result.message or "", if result.ok then "success" else "error")
	end)
	rows[entry.id] = { description = description, button = button }
end

-- Вікно зі списком покращень однієї валюти
local function buildPanel(gui, panelName, title, color, currency, hint)
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
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 10), SortOrder = Enum.SortOrder.LayoutOrder, Parent = list })
	UIKit.Create("UIPadding", { PaddingTop = UDim.new(0, 4), PaddingLeft = UDim.new(0, 4), Parent = list })
	UIKit.Label({
		LayoutOrder = 0,
		Size = UDim2.new(1, -12, 0, 26),
		TextSize = 16,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = hint,
		Parent = list,
	})
	for index, entry in ENTRIES do
		if entry.currency == currency then
			buildRow(list, index, entry)
		end
	end
	return newPanel
end

function UpgradesUI.Init(gui)
	local upgradesPanel = buildPanel(gui, "Upgrades", "⬆️ Upgrades", Color3.fromRGB(70, 205, 100), "Coins", "Покращення бази за 🪙 Coins")
	local shopPanel = buildPanel(gui, "Shop", "💎 Crystal Shop", Color3.fromRGB(60, 205, 85), "Crystals", "💎 Кристали дають боси, завдання, колекція та Rebirth")

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
