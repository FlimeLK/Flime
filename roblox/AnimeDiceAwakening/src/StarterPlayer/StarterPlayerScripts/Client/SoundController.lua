-- SoundController: звуки інтерфейсу. ID звуків — у Config/AssetConfig.
-- Звук грає лише якщо його ID заповнено і в налаштуваннях увімкнено "Звук".

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local SoundService = game:GetService("SoundService")

local AssetConfig = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"):WaitForChild("AssetConfig"))

local Client = script.Parent
local ClientState = require(Client:WaitForChild("ClientState"))

local SoundController = {}

local sounds = {} -- [key] = Sound

function SoundController.Play(key, pitch)
	local soundId = AssetConfig.GetSound(key)
	if not soundId then
		return
	end
	-- Поки дані не прийшли, звук дозволено; далі — за налаштуванням
	if ClientState.Data and not ClientState.GetSetting("sound") then
		return
	end
	local sound = sounds[key]
	if not sound then
		sound = Instance.new("Sound")
		sound.Name = "UI_" .. key
		sound.SoundId = soundId
		sound.Volume = AssetConfig.SoundVolume[key] or 0.5
		sound.Parent = SoundService
		sounds[key] = sound
	end
	sound.PlaybackSpeed = pitch or 1
	SoundService:PlayLocalSound(sound)
end

return SoundController
