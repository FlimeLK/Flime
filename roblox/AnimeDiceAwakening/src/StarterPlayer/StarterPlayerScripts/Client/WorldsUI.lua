-- WorldsUI: список світів і кнопки подорожі. Переносить гравця сервер.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local WorldConfig = require(Shared:WaitForChild("Config"):WaitForChild("WorldConfig"))
local GameMath = require(Shared:WaitForChild("GameMath"))

local Client = script.Parent
local UIKit = require(Client:WaitForChild("UIKit"))
local ClientState = require(Client:WaitForChild("ClientState"))
local Hud = require(Client:WaitForChild("Hud"))

local player = Players.LocalPlayer

local WorldsUI = {}

local rows = {} -- [worldId] = { frame, button }

local function travel(worldId, panel)
	local result = ClientState.Request("Travel", worldId)
	UIKit.Toast(result.message or "", if result.ok then "success" else "error")
	if result.ok then
		panel.Visible = false
	end
end

local function refresh()
	local current = player:GetAttribute("World") or "Lobby"
	local data = ClientState.Data
	for worldId, row in rows do
		local here = worldId == current
		row.stroke.Color = if here then Color3.new(1, 1, 1) else row.color
		row.stroke.Thickness = if here then 3 else 2
		if row.available then
			local unlocked, requirement = true, nil
			if worldId ~= "Lobby" and data then
				unlocked, requirement = GameMath.IsWorldUnlocked(data, worldId)
			end
			row.locked = not unlocked
			if not unlocked then
				row.button.Text = "🔒 Закрито"
				row.button.BackgroundColor3 = UIKit.Colors.Disabled
				row.subtitle.Text = "Щоб відкрити: " .. requirement
			else
				row.button.Text = if here then "📍 Ти тут" else "▶ Travel"
				row.button.BackgroundColor3 = if here then UIKit.Colors.Disabled else UIKit.Colors.Success
				row.subtitle.Text = row.description
			end
		end
	end
end

local function addRow(content, order, worldId, title, subtitle, color, available, panel)
	local frame = UIKit.Create("Frame", {
		LayoutOrder = order,
		Size = UDim2.new(1, 0, 0, 58),
		BackgroundColor3 = color:Lerp(UIKit.Colors.Background, 0.75),
		Parent = content,
	})
	UIKit.Corner(frame, 12)
	local stroke = UIKit.Stroke(frame, color, 2)
	UIKit.Label({
		Position = UDim2.fromOffset(14, 2),
		Size = UDim2.new(1, -200, 0, 30),
		Font = UIKit.Font,
		TextSize = 22,
		TextColor3 = color:Lerp(Color3.new(1, 1, 1), 0.3),
		TextXAlignment = Enum.TextXAlignment.Left,
		Text = title,
		Parent = frame,
	})
	local subtitleLabel = UIKit.Label({
		Position = UDim2.fromOffset(14, 31),
		Size = UDim2.new(1, -200, 0, 22),
		TextSize = 14,
		TextColor3 = UIKit.Colors.SubText,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextTruncate = Enum.TextTruncate.AtEnd,
		Text = subtitle,
		Parent = frame,
	})
	local row = { stroke = nil, button = nil, color = color, available = available, subtitle = subtitleLabel, description = subtitle, locked = false }
	local button = UIKit.Button({
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -10, 0.5, 0),
		Size = UDim2.fromOffset(170, 44),
		BackgroundColor3 = if available then UIKit.Colors.Success else UIKit.Colors.Disabled,
		Text = if available then "▶ Travel" else "🔒 Скоро",
		TextSize = 19,
		Parent = frame,
	}, function()
		if not available then
			UIKit.Toast("Цей світ відкриється в наступних оновленнях", "info")
		elseif row.locked then
			UIKit.Toast(row.subtitle.Text, "error")
		else
			travel(worldId, panel)
		end
	end)
	row.stroke = stroke
	row.button = button
	rows[worldId] = row
end

function WorldsUI.Init(gui)
	local panel, content = UIKit.Panel(gui, "Worlds", "🌍 Worlds")
	Hud.RegisterPanel("Worlds", panel)
	UIKit.Create("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder, Parent = content })

	addRow(content, 0, "Lobby", "🏠 Lobby", "Твоя база та кубики", UIKit.Colors.Accent, true, panel)
	for index, worldId in WorldConfig.Order do
		local world = WorldConfig.Worlds[worldId]
		addRow(content, index, worldId, world.displayName .. " — " .. world.localName, world.description, world.color, world.available, panel)
	end

	refresh()
	player:GetAttributeChangedSignal("World"):Connect(refresh)
	ClientState.OnDataChanged(refresh)
end

return WorldsUI
