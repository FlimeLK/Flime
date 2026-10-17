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
