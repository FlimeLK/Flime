-- ZoneGates: ворота зон на екрані цього гравця.
-- Відкрита зона — ворота стають прозорими й прохідними (тільки для нього:
-- персонажем керує його клієнт). Закрита — показуємо прогрес перемог.

local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local GameMath = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("GameMath"))

local Client = script.Parent
local ClientState = require(Client:WaitForChild("ClientState"))

local ZoneGates = {}

local GATE_TAG = "ZoneGate" -- той самий тег, що у WorldService

local function apply(gate)
	local data = ClientState.Data
	if not data then
		return
	end
	local zoneIndex = gate:GetAttribute("ZoneIndex")
	local unlocked = GameMath.IsZoneUnlocked(data, gate:GetAttribute("World"), zoneIndex)
	gate.CanCollide = not unlocked
	gate.Transparency = if unlocked then 0.9 else 0.3

	local sign = gate:FindFirstChild("Sign")
	local label = sign and sign:FindFirstChild("Gui") and sign.Gui:FindFirstChild("Label")
	if label then
		local name = gate:GetAttribute("ZoneName") or "?"
		if unlocked then
			label.Text = "✅ " .. name
		else
			local kills = GameMath.GetWorldKills(data, gate:GetAttribute("World"))
			label.Text = ("🔒 %s — перемоги тут: %d / %d"):format(name, kills, gate:GetAttribute("RequiredKills") or 0)
		end
	end
end

local function applyAll()
	for _, gate in CollectionService:GetTagged(GATE_TAG) do
		apply(gate)
	end
end

function ZoneGates.Init()
	CollectionService:GetInstanceAddedSignal(GATE_TAG):Connect(apply)
	ClientState.OnDataChanged(applyAll)
	applyAll()
end

return ZoneGates
