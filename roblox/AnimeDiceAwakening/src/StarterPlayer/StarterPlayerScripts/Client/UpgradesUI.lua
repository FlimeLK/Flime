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
local panel = nil

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
	for _, entry in ENTRIES do
		local row = rows[entry.id]
		row.description.Text = entry.describe(data, now)
		local price = entry.getPrice(data, now)
		if price then
			local icon = if entry.currency == "Crystals" then "💎" else "🪙"
			local balance = if entry.currency == "Crystals" then ClientState.Crystals else ClientState.Coins
			row.button.Text = ("Buy %s %s"):format(icon, GameMath.FormatNumber(price))
			row.button.BackgroundColor3 = if balance >= price
				then (if entry.currency == "Crystals" then UIKit.Colors.Accent2 else UIKit.Colors.Success)
				else UIKit.Colors.Disabled
		else
			row.button.Text = "MAX"
			row.button.BackgroundColor3 = UIKit.Colors.Disabled
		end
	end
end

local function sectionHeader(parent, order, text)
	UIKit.Label({
		LayoutOrder = order,
		Size = UDim2.new(1, -12, 0, 28),
		Font = UIKit.Font,
		TextSize = 21,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = text,
		Parent = parent,
	})
end

function UpgradesUI.Init(gui)
	local content
	panel, content = UIKit.Panel(gui, "Upgrades", "⬆️ Upgrades & Shop")
	Hud.RegisterPanel("Upgrades", panel)

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
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 8), SortOrder = Enum.SortOrder.LayoutOrder, Parent = list })

	sectionHeader(list, 0, "🪙 Покращення бази")
	local shopHeaderAdded = false
	for index, entry in ENTRIES do
		if entry.currency == "Crystals" and not shopHeaderAdded then
			sectionHeader(list, index * 2 - 1, "💎 Crystal Shop — кристали дають боси, завдання й колекція")
			shopHeaderAdded = true
		end
		local row = UIKit.Create("Frame", {
			LayoutOrder = index * 2,
			Size = UDim2.new(1, -12, 0, 84),
			BackgroundColor3 = UIKit.Colors.Background,
			BackgroundTransparency = 0.3,
			Parent = list,
		})
		UIKit.Corner(row, 14)
		UIKit.Label({
			Position = UDim2.fromOffset(16, 6),
			Size = UDim2.new(1, -250, 0, 32),
			Font = UIKit.Font,
			TextSize = 23,
			TextXAlignment = Enum.TextXAlignment.Left,
			Text = entry.title,
			Parent = row,
		})
		local description = UIKit.Label({
			Position = UDim2.fromOffset(16, 40),
			Size = UDim2.new(1, -250, 0, 38),
			TextSize = 15,
			TextColor3 = UIKit.Colors.SubText,
			TextXAlignment = Enum.TextXAlignment.Left,
			Parent = row,
		})
		local button = UIKit.Button({
			AnchorPoint = Vector2.new(1, 0.5),
			Position = UDim2.new(1, -14, 0.5, 0),
			Size = UDim2.fromOffset(210, 58),
			TextSize = 21,
			Parent = row,
		}, function()
			local result = ClientState.Request(entry.remote, entry.id)
			UIKit.Toast(result.message or "", if result.ok then "success" else "error")
		end)
		rows[entry.id] = { description = description, button = button }
	end

	ClientState.OnDataChanged(refresh)
	ClientState.OnCurrencyChanged(refresh)
	-- Таймери зілля
	task.spawn(function()
		while true do
			task.wait(1)
			if panel.Visible then
				refresh()
			end
		end
	end)
end

return UpgradesUI
