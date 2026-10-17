-- RollService: кидки кубиків. Результат визначає ТІЛЬКИ сервер;
-- клієнт отримує вже готовий результат і лише показує анімацію.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local DiceConfig = require(Shared.Config.DiceConfig)
local EconomyConfig = require(Shared.Config.EconomyConfig)
local HeroConfig = require(Shared.Config.HeroConfig)
local RarityConfig = require(Shared.Config.RarityConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)
local InventoryService = require(script.Parent.InventoryService)
local QuestService = require(script.Parent.QuestService)
local RateLimiter = require(script.Parent.RateLimiter)

local RollService = {}

local rng = Random.new()
local limiter = RateLimiter.new(4, 2.5)
local lastRollTime = setmetatable({}, { __mode = "k" })

-- Вибір ключа за вагами. keys — впорядкований список ключів.
local function weightedPick(weights, keys)
	local total = 0
	for _, key in keys do
		total += weights[key] or 0
	end
	if total <= 0 then
		return nil
	end
	local roll = rng:NextNumber() * total
	local lastValid = nil
	for _, key in keys do
		local weight = weights[key] or 0
		if weight > 0 then
			lastValid = key
			if roll < weight then
				return key
			end
			roll -= weight
		end
	end
	return lastValid -- захист від похибки округлення
end

-- Найвища рідкість, яку гарантує система pity на цьому кидку (0 — немає).
local function getGuaranteedRank(data)
	local rank = 0
	for _, tier in EconomyConfig.Pity do
		local count = data.pity[tier.rarity] or 0
		if count + 1 >= tier.rolls then
			rank = math.max(rank, RarityConfig.GetRank(tier.rarity))
		end
	end
	return rank
end

local function pickRarity(data, dice)
	-- Удача гравця (зілля удачі) множиться на удачу кубика
	local weights = GameMath.GetRarityWeights(dice, GameMath.GetLuck(data, os.time()))
	local rarity = weightedPick(weights, RarityConfig.Order) or "Common"
	local pityUsed = false

	local guaranteedRank = getGuaranteedRank(data)
	if RarityConfig.GetRank(rarity) < guaranteedRank then
		local filtered = {}
		for _, name in RarityConfig.Order do
			filtered[name] = if RarityConfig.GetRank(name) >= guaranteedRank then weights[name] else 0
		end
		local guaranteed = weightedPick(filtered, RarityConfig.Order)
		if guaranteed then
			rarity = guaranteed
			pityUsed = true
		end
	end

	-- Оновлюємо лічильники гарантії
	local rank = RarityConfig.GetRank(rarity)
	for _, tier in EconomyConfig.Pity do
		if rank >= RarityConfig.GetRank(tier.rarity) then
			data.pity[tier.rarity] = 0
		else
			data.pity[tier.rarity] = (data.pity[tier.rarity] or 0) + 1
		end
	end
	return rarity, pityUsed
end

local function pickHero(rarity, dice)
	local weights, keys = {}, {}
	for _, heroDef in HeroConfig.ByRarity[rarity] or {} do
		table.insert(keys, heroDef.id)
		weights[heroDef.id] = if dice.element and heroDef.element == dice.element then dice.elementBonus else 1
	end
	return weightedPick(weights, keys)
end

local function fail(message)
	return { ok = false, message = message }
end

local function onRoll(player, diceId)
	if typeof(diceId) ~= "string" then
		return fail("Невірний кубик")
	end
	local dice = DiceConfig.Dice[diceId]
	if not dice then
		return fail("Невірний кубик")
	end
	if not limiter:Check(player) then
		return fail("Занадто швидко!")
	end
	local now = os.clock()
	if lastRollTime[player] and now - lastRollTime[player] < EconomyConfig.RollCooldown then
		return fail("Зачекай мить...")
	end

	local data = DataService.Get(player)
	if not data then
		return fail("Дані ще завантажуються")
	end
	local unlocked, requirement = GameMath.IsDiceUnlocked(data, dice)
	if not unlocked then
		return fail("Кубик закритий: " .. requirement)
	end
	if InventoryService.CountHeroes(data) >= GameMath.GetMaxInventory(data) then
		return fail("Інвентар заповнений! Продай або злий зайвих героїв.")
	end

	local isFree = not data.tutorial.freeRollUsed and diceId == DiceConfig.TutorialDice
	if not isFree and not DataService.SpendCoins(player, dice.price) then
		return fail("Не вистачає монет")
	end
	if isFree then
		data.tutorial.freeRollUsed = true
	end
	lastRollTime[player] = now

	local rarity, pityUsed = pickRarity(data, dice)
	local heroId = pickHero(rarity, dice)
	local isNew = not data.discovered[heroId]
	local uid = InventoryService.GiveHero(player, heroId)
	data.totalRolls += 1
	QuestService.Track(player, "roll")
	DataService.MarkChanged(player)

	return {
		ok = true,
		uid = uid,
		heroId = heroId,
		rarity = rarity,
		isNew = isNew,
		pity = pityUsed,
		free = isFree,
	}
end

function RollService.Init()
	-- Перевірка конфігурації при старті: у кожної рідкості мають бути герої.
	for _, rarity in RarityConfig.Order do
		assert(HeroConfig.ByRarity[rarity] and #HeroConfig.ByRarity[rarity] > 0, "No heroes for rarity " .. rarity)
	end
	Remotes.Handle("RollDice", onRoll)
end

return RollService
