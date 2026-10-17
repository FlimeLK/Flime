-- SettingsService: збереження налаштувань гравця (звук, ефекти, пропуск анімацій).

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local RateLimiter = require(script.Parent.RateLimiter)

local SettingsService = {}

local limiter = RateLimiter.new(6, 2)

local ALLOWED = {
	sound = true,
	effects = true,
	skipAnimations = true,
}

local function onSetSetting(player, key, value)
	if typeof(key) ~= "string" or not ALLOWED[key] or typeof(value) ~= "boolean" then
		return { ok = false, message = "Невірне налаштування" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end
	data.settings[key] = value
	return { ok = true }
end

function SettingsService.Init()
	Remotes.Handle("SetSetting", onSetSetting)
end

return SettingsService
