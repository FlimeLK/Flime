-- WorldLighting: освітлення світу на екрані цього гравця.
-- У світах з night = true (WorldConfig) настає неонова ніч; в інших — звичайний день.

local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local WorldConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("WorldConfig"))

local player = Players.LocalPlayer

local WorldLighting = {}

local NIGHT = {
	ClockTime = 0,
	Brightness = 1,
	Ambient = Color3.fromRGB(70, 40, 110),
	OutdoorAmbient = Color3.fromRGB(80, 50, 130),
	FogColor = Color3.fromRGB(40, 15, 60),
	FogEnd = 600,
}

local day = nil -- значення освітлення до входу в нічний світ

local function apply()
	local worldId = player:GetAttribute("World")
	local world = worldId and WorldConfig.Worlds[worldId]
	local wantNight = world ~= nil and world.night == true
	if wantNight then
		if not day then
			day = {}
			for key in NIGHT do
				day[key] = Lighting[key]
			end
		end
		TweenService:Create(Lighting, TweenInfo.new(1.2), NIGHT):Play()
	elseif day then
		TweenService:Create(Lighting, TweenInfo.new(1.2), day):Play()
		day = nil
	end
end

function WorldLighting.Init()
	player:GetAttributeChangedSignal("World"):Connect(apply)
	apply()
end

return WorldLighting
