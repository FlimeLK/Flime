-- UpgradesUI: покупка нових слотів бази та покращення доходу.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared:WaitForChild("Config"):WaitForChild("EconomyConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local UpgradesUI = {}

local rows = {}

local UPGRADES = {
	{
		id = "Slots",
		title = "🧱 Слоти бази",
		describe = function(data)
			return ("Слотів: %d / %d. Більше героїв на базі — більше монет."):format(data.slotCount, EconomyConfig.MaxSlots)
		end,
		getPrice = function(data)
			return GameMath.GetSlotPrice(data.slotCount)
		end,
	},
	{
		id = "Income",
		title = "💰 Дохід бази",
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
	},
}

local function refresh()
	local data = ClientState.Data
	if not data then
		return
	end
	for _, upgrade in UPGRADES do
		local row = rows[upgrade.id]
		row.description.Text = upgrade.describe(data)
		local price = upgrade.getPrice(data)
		if price then
			row.button.Text = "Buy 🪙 " .. GameMath.FormatNumber(price)
			row.button.BackgroundColor3 = if ClientState.Coins >= price then UIKit.Colors.Success else UIKit.Colors.Disabled
		else
			row.button.Text = "MAX"
			row.button.BackgroundColor3 = UIKit.Colors.Disabled
		end
	end
end

function UpgradesUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Upgrades", "⬆️ Upgrades")
	Hud.RegisterPanel("Upgrades", panel)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 12), SortOrder = Enum.SortOrder.LayoutOrder, Parent = content })

	for index, upgrade in UPGRADES do
		local row = UIKit.Create("Frame", {
			LayoutOrder = index,
			Size = UDim2.new(1, 0, 0, 100),
			BackgroundColor3 = UIKit.Colors.Background,
			BackgroundTransparency = 0.3,
			Parent = content,
		})
		UIKit.Corner(row, 14)
		UIKit.Label({
			Position = UDim2.fromOffset(16, 10),
			Size = UDim2.new(1, -260, 0, 36),
			Font = UIKit.Font,
			TextSize = 26,
			TextXAlignment = Enum.TextXAlignment.Left,
			Text = upgrade.title,
			Parent = row,
		})
		local description = UIKit.Label({
			Position = UDim2.fromOffset(16, 48),
			Size = UDim2.new(1, -260, 0, 44),
			TextSize = 16,
			TextColor3 = UIKit.Colors.SubText,
			TextXAlignment = Enum.TextXAlignment.Left,
			Parent = row,
		})
		local button = UIKit.Button({
			AnchorPoint = Vector2.new(1, 0.5),
			Position = UDim2.new(1, -16, 0.5, 0),
			Size = UDim2.fromOffset(220, 64),
			TextSize = 22,
			Parent = row,
		}, function()
			local result = ClientState.Request("BuyUpgrade", upgrade.id)
			UIKit.Toast(result.message or "", if result.ok then "success" else "error")
		end)
		rows[upgrade.id] = { description = description, button = button }
	end

	ClientState.OnDataChanged(refresh)
	ClientState.OnCurrencyChanged(refresh)
end

return UpgradesUI
