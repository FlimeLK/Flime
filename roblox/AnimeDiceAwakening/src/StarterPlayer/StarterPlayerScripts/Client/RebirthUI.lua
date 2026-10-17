-- RebirthUI: вікно Rebirth — прогрес до наступного Rebirth, що отримаєш і що скинеться.
-- Підтвердження вимагає двох натискань, щоб не зробити Rebirth випадково.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared:WaitForChild("Config"):WaitForChild("EconomyConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local RebirthUI = {}

local ui: { [string]: any } = {}
local confirmUntil = 0

local function infoCard(parent, position, title, color)
	local card = UIKit.Create("Frame", {
		Position = position,
		Size = UDim2.new(0.5, -8, 0, 150),
		BackgroundColor3 = UIKit.Colors.Background,
		BackgroundTransparency = 0.15,
		Parent = parent,
	})
	UIKit.Corner(card, 16)
	UIKit.Stroke(card, color, 3)
	UIKit.Label({
		Position = UDim2.fromOffset(12, 6),
		Size = UDim2.new(1, -24, 0, 30),
		Font = UIKit.Font,
		TextSize = 22,
		TextColor3 = color,
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = title,
		Parent = card,
	})
	return UIKit.Label({
		Position = UDim2.fromOffset(12, 38),
		Size = UDim2.new(1, -24, 1, -44),
		TextSize = 16,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextYAlignment = Enum.TextYAlignment.Top,
		Parent = card,
	})
end

local function refresh()
	local data = ClientState.Data
	if not data then
		return
	end
	local rebirths = data.rebirths or 0
	local cost = GameMath.GetRebirthCost(rebirths)
	local coins = ClientState.Coins
	local ready = coins >= cost

	ui.count.Text = ("♻️ Rebirth: %d"):format(rebirths)
	ui.current.Text = ("Зараз: дохід ×%.1f • удача ×%.2f"):format(GameMath.GetRebirthIncome(rebirths), GameMath.GetRebirthLuck(rebirths))
	ui.fill.Size = UDim2.fromScale(math.clamp(coins / cost, 0, 1), 1)
	ui.progress.Text = ("🪙 %s / %s"):format(GameMath.FormatNumber(coins), GameMath.FormatNumber(cost))

	local nextRebirth = rebirths + 1
	ui.gain.Text = ("💰 Дохід ×%.1f назавжди\n🍀 Удача ×%.2f назавжди\n💎 +%d кристалів"):format(
		GameMath.GetRebirthIncome(nextRebirth),
		GameMath.GetRebirthLuck(nextRebirth),
		EconomyConfig.Rebirth.crystalReward * nextRebirth
	)

	if os.clock() < confirmUntil then
		ui.button.Text = "⚠️ Точно? Натисни ще раз!"
		ui.button.BackgroundColor3 = UIKit.Colors.Danger
	elseif ready then
		ui.button.Text = "♻️ REBIRTH!"
		ui.button.BackgroundColor3 = Hud.Colors.Rebirth
	else
		ui.button.Text = "Потрібно ще 🪙 " .. GameMath.FormatNumber(cost - coins)
		ui.button.BackgroundColor3 = UIKit.Colors.Disabled
	end
	Hud.SetBadge("Rebirth", ready)
end

function RebirthUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Rebirth", "♻️ Rebirth", Hud.Colors.Rebirth)
	Hud.RegisterPanel("Rebirth", panel)

	ui.count = UIKit.Label({
		Size = UDim2.new(0.5, 0, 0, 36),
		Font = UIKit.Font,
		TextSize = 30,
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = content,
	})
	ui.current = UIKit.Label({
		Position = UDim2.new(0.5, 0, 0, 0),
		Size = UDim2.new(0.5, 0, 0, 36),
		Font = UIKit.Font,
		TextSize = 19,
		TextColor3 = UIKit.Colors.Gold,
		TextXAlignment = Enum.TextXAlignment.Right,
		Parent = content,
	})

	local back = UIKit.Create("Frame", {
		Position = UDim2.fromOffset(0, 46),
		Size = UDim2.new(1, 0, 0, 34),
		BackgroundColor3 = UIKit.Colors.Background,
		Parent = content,
	})
	UIKit.Corner(back, 12)
	UIKit.Stroke(back, UIKit.Colors.Outline, 3)
	ui.fill = UIKit.Create("Frame", { Size = UDim2.fromScale(0, 1), BackgroundColor3 = UIKit.Colors.Money, Parent = back })
	UIKit.Corner(ui.fill, 12)
	UIKit.Shade(ui.fill, 0.35)
	ui.progress = UIKit.Label({ Size = UDim2.fromScale(1, 1), Font = UIKit.Font, TextSize = 20, Parent = back })

	ui.gain = infoCard(content, UDim2.fromOffset(0, 94), "✅ Отримаєш", UIKit.Colors.Success)
	infoCard(content, UDim2.new(0.5, 8, 0, 94), "❌ Скинеться", UIKit.Colors.Danger).Text =
		"🪙 Монети → " .. EconomyConfig.StartingCoins .. "\n🧱 Слоти бази → " .. EconomyConfig.StartSlots .. "\n💰 Рівень доходу → 0\nГерої, команда, 💎 і світи залишаться!"

	ui.button = UIKit.Button({
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.fromScale(0.5, 1),
		Size = UDim2.fromOffset(400, 70),
		TextSize = 30,
		Parent = content,
	}, function()
		local data = ClientState.Data
		if not data or ClientState.Coins < GameMath.GetRebirthCost(data.rebirths or 0) then
			UIKit.Toast("Ще не вистачає монет для Rebirth", "error")
			return
		end
		if os.clock() >= confirmUntil then
			confirmUntil = os.clock() + 3
			refresh()
			task.delay(3.05, refresh)
			return
		end
		confirmUntil = 0
		local result = ClientState.Request("Rebirth")
		UIKit.Toast(result.message or "", if result.ok then "success" else "error")
		refresh()
	end)
	ui.button.TextOutline.Thickness = 3

	ClientState.OnDataChanged(refresh)
	ClientState.OnCurrencyChanged(refresh)
end

return RebirthUI
