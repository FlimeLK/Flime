-- WorldLighting: освітлення й атмосфера на екрані цього гравця.
-- Кожна локація має свій настрій: яскравий день у лобі, захід сонця в селі ніндзя,
-- тропічний полудень на острові, неонова ніч у місті демонів.

local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local WorldConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("WorldConfig"))

local player = Players.LocalPlayer

local WorldLighting = {}

-- Lighting — властивості Lighting; Atmosphere / ColorCorrection / Bloom / SunRays — однойменних ефектів
local PRESETS = {
	Lobby = {
		Lighting = { ClockTime = 14.5, Brightness = 2.4, Ambient = Color3.fromRGB(110, 105, 130), OutdoorAmbient = Color3.fromRGB(150, 145, 170), FogColor = Color3.fromRGB(200, 225, 255), FogEnd = 100000 },
		Atmosphere = { Density = 0.3, Offset = 0.15, Color = Color3.fromRGB(205, 225, 255), Decay = Color3.fromRGB(150, 175, 230), Glare = 0.3, Haze = 1.2 },
		ColorCorrection = { Brightness = 0.02, Contrast = 0.08, Saturation = 0.18, TintColor = Color3.fromRGB(255, 250, 255) },
		Bloom = { Intensity = 0.6, Size = 28, Threshold = 1.6 },
		SunRays = { Intensity = 0.08, Spread = 0.8 },
	},
	NinjaVillage = {
		Lighting = { ClockTime = 17.2, Brightness = 2.2, Ambient = Color3.fromRGB(125, 95, 95), OutdoorAmbient = Color3.fromRGB(170, 130, 120), FogColor = Color3.fromRGB(255, 200, 170), FogEnd = 100000 },
		Atmosphere = { Density = 0.38, Offset = 0.2, Color = Color3.fromRGB(255, 205, 175), Decay = Color3.fromRGB(230, 140, 120), Glare = 0.6, Haze = 1.8 },
		ColorCorrection = { Brightness = 0.02, Contrast = 0.1, Saturation = 0.15, TintColor = Color3.fromRGB(255, 240, 230) },
		Bloom = { Intensity = 0.8, Size = 30, Threshold = 1.4 },
		SunRays = { Intensity = 0.15, Spread = 0.9 },
	},
	PirateIsland = {
		Lighting = { ClockTime = 12.8, Brightness = 2.8, Ambient = Color3.fromRGB(110, 120, 135), OutdoorAmbient = Color3.fromRGB(150, 170, 190), FogColor = Color3.fromRGB(200, 235, 255), FogEnd = 100000 },
		Atmosphere = { Density = 0.33, Offset = 0.1, Color = Color3.fromRGB(195, 235, 255), Decay = Color3.fromRGB(120, 190, 240), Glare = 0.2, Haze = 1.4 },
		ColorCorrection = { Brightness = 0.03, Contrast = 0.08, Saturation = 0.25, TintColor = Color3.fromRGB(250, 255, 255) },
		Bloom = { Intensity = 0.5, Size = 24, Threshold = 1.7 },
		SunRays = { Intensity = 0.1, Spread = 0.6 },
	},
	DemonCity = {
		Lighting = { ClockTime = 0, Brightness = 1, Ambient = Color3.fromRGB(70, 40, 110), OutdoorAmbient = Color3.fromRGB(80, 50, 130), FogColor = Color3.fromRGB(40, 15, 60), FogEnd = 100000 },
		Atmosphere = { Density = 0.45, Offset = 0.05, Color = Color3.fromRGB(90, 40, 130), Decay = Color3.fromRGB(40, 10, 70), Glare = 0, Haze = 2.2 },
		ColorCorrection = { Brightness = 0, Contrast = 0.15, Saturation = 0.3, TintColor = Color3.fromRGB(240, 225, 255) },
		Bloom = { Intensity = 1.2, Size = 36, Threshold = 0.9 },
		SunRays = { Intensity = 0, Spread = 0.5 },
	},
}
-- Світи без власного пресету (MagicAcademy, SkyArena) беруть денний; нічні — нічний
local DEFAULT_DAY, DEFAULT_NIGHT = PRESETS.Lobby, PRESETS.DemonCity

local effects = {}

-- Беремо ефект, що вже є в Lighting (шаблони Studio додають Atmosphere, Bloom, SunRays), або створюємо свій
local function ensureEffect(className)
	local effect = Lighting:FindFirstChildOfClass(className)
	if not effect then
		effect = Instance.new(className)
		effect.Parent = Lighting
	end
	return effect
end

local function apply(instant)
	local worldId = player:GetAttribute("World") or "Lobby"
	local preset = PRESETS[worldId]
	if not preset then
		local world = WorldConfig.Worlds[worldId]
		preset = if world and world.night then DEFAULT_NIGHT else DEFAULT_DAY
	end
	local info = TweenInfo.new(if instant then 0 else 1.2, Enum.EasingStyle.Sine)
	TweenService:Create(Lighting, info, preset.Lighting):Play()
	for key, props in preset do
		local effect = effects[key]
		if effect then
			TweenService:Create(effect, info, props):Play()
		end
	end
end

function WorldLighting.Init()
	Lighting.GlobalShadows = true
	Lighting.EnvironmentDiffuseScale = 1
	Lighting.EnvironmentSpecularScale = 1
	Lighting.ShadowSoftness = 0.25
	effects.Atmosphere = ensureEffect("Atmosphere")
	effects.ColorCorrection = ensureEffect("ColorCorrectionEffect")
	effects.Bloom = ensureEffect("BloomEffect")
	effects.SunRays = ensureEffect("SunRaysEffect")
	player:GetAttributeChangedSignal("World"):Connect(function()
		apply(false)
	end)
	apply(true)
end

return WorldLighting
