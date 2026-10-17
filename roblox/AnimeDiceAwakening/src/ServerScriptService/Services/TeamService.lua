-- TeamService: бойова команда з 3 героїв.
-- Один герой — або на базі, або в команді: додаючи героя з бази до команди,
-- сервер сам знімає його з бази.
--
-- Склад команди сервер записує в атрибут гравця "TeamData", щоб усі клієнти
-- могли намалювати героїв-супутників ("heroId:level;heroId:level;").

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local CombatConfig = require(Shared.Config.CombatConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)
local RateLimiter = require(script.Parent.RateLimiter)

local TeamService = {}

local limiter = RateLimiter.new(8, 4)

local function findTeamSlot(data, uid)
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == uid then
			return i
		end
	end
	return nil
end

local function removeFromBase(data, uid)
	for i = 1, data.slotCount do
		if data.slots[i] == uid then
			data.slots[i] = ""
			return true
		end
	end
	return false
end

-- Обробники: (data, uid) -> ok, message, baseChanged
local actions = {}

function actions.Add(data, uid)
	if findTeamSlot(data, uid) then
		return false, "Герой уже в команді"
	end
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == "" then
			local fromBase = removeFromBase(data, uid)
			data.team[i] = uid
			return true, if fromBase then "Героя знято з бази й додано до команди" else "Героя додано до команди", fromBase
		end
	end
	return false, ("Команда заповнена (%d/%d). Спершу прибери когось"):format(CombatConfig.TeamSize, CombatConfig.TeamSize)
end

function actions.Remove(data, uid)
	local slot = findTeamSlot(data, uid)
	if not slot then
		return false, "Цього героя немає в команді"
	end
	data.team[slot] = ""
	return true, "Героя прибрано з команди"
end

-- Найсильніші герої за шкодою, крім тих, що стоять на базі.
local function bestTeam(data)
	local list = {}
	for uid, hero in data.heroes do
		local heroDef = HeroConfig.Heroes[hero.id]
		if heroDef and not GameMath.IsOnBase(data, uid) then
			table.insert(list, { uid = uid, dps = GameMath.GetHeroDps(heroDef, hero.level, hero.awakened) })
		end
	end
	if #list == 0 then
		return false, "Немає вільних героїв (герої на базі не враховуються)"
	end
	table.sort(list, function(a, b)
		if a.dps ~= b.dps then
			return a.dps > b.dps
		end
		return a.uid < b.uid
	end)
	for i = 1, CombatConfig.TeamSize do
		data.team[i] = if list[i] then list[i].uid else ""
	end
	return true, "Найсильнішу команду зібрано (герої на базі не враховуються)"
end

local function clearTeam(data)
	for i = 1, CombatConfig.TeamSize do
		data.team[i] = ""
	end
	return true, "Команду розпущено"
end

-- "riku_windstep:3;;seren_starblade:1:A" (":A" — пробуджений)
function TeamService.Encode(data)
	local parts = {}
	for i = 1, CombatConfig.TeamSize do
		local uid = data.team[i]
		local hero = uid ~= "" and data.heroes[uid]
		parts[i] = if hero then hero.id .. ":" .. hero.level .. (if hero.awakened then ":A" else "") else ""
	end
	return table.concat(parts, ";")
end

local function onTeamAction(player, action, uid)
	if typeof(action) ~= "string" then
		return { ok = false, message = "Невідома дія" }
	end
	if not limiter:Check(player) then
		return { ok = false, message = "Занадто швидко!" }
	end
	local data = DataService.Get(player)
	if not data then
		return { ok = false, message = "Дані ще завантажуються" }
	end

	local ok, message, baseChanged
	if action == "Best" then
		ok, message = bestTeam(data)
	elseif action == "Clear" then
		ok, message = clearTeam(data)
	elseif actions[action] then
		if typeof(uid) ~= "string" or #uid > 24 then
			return { ok = false, message = "Невірний герой" }
		end
		local hero = data.heroes[uid]
		if not hero or not HeroConfig.Heroes[hero.id] then
			return { ok = false, message = "Героя не знайдено" }
		end
		ok, message, baseChanged = actions[action](data, uid)
	else
		return { ok = false, message = "Невідома дія" }
	end

	if ok then
		DataService.MarkChanged(player)
		if baseChanged then
			PlotService.RefreshPlot(player)
		end
	end
	return { ok = ok, message = message }
end

function TeamService.Init()
	Remotes.Handle("TeamAction", onTeamAction)
	-- Після будь-якої зміни даних (рівень героя, продаж, Place) оновлюємо супутників
	DataService.OnChanged(function(player, data)
		local encoded = TeamService.Encode(data)
		if player:GetAttribute("TeamData") ~= encoded then
			player:SetAttribute("TeamData", encoded)
		end
	end)
end

return TeamService
