-- GameMath: формули балансу, спільні для сервера й клієнта.
-- Сервер використовує їх для справжніх розрахунків, клієнт — лише для показу,
-- тому цифри в інтерфейсі завжди збігаються з тим, що рахує сервер.

local Config = script.Parent:WaitForChild("Config")
local RarityConfig = require(Config:WaitForChild("RarityConfig"))
local EconomyConfig = require(Config:WaitForChild("EconomyConfig"))
local HeroConfig = require(Config:WaitForChild("HeroConfig"))
local CombatConfig = require(Config:WaitForChild("CombatConfig"))
local ShopConfig = require(Config:WaitForChild("ShopConfig"))
local WorldConfig = require(Config:WaitForChild("WorldConfig"))
local EnemyConfig = require(Config:WaitForChild("EnemyConfig"))

local GameMath = {}

-- Ваги рідкостей з урахуванням удачі кубика та гравця.
function GameMath.GetRarityWeights(dice, playerLuck)
	local luck = dice.luck * (playerLuck or 1)
	local weights = {}
	local total = 0
	for _, rarity in RarityConfig.Order do
		local weight = dice.weights[rarity] or 0
		if RarityConfig.Info[rarity].luckAffected then
			weight *= luck
		end
		weights[rarity] = weight
		total += weight
	end
	return weights, total
end

-- Шанси у відсотках: { Common = 70.1, Rare = 23.0, ... }
function GameMath.GetChances(dice, playerLuck)
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	local chances = {}
	for rarity, weight in weights do
		chances[rarity] = if total > 0 then weight / total * 100 else 0
	end
	return chances
end

-- Шанс випасти саме цьому герою з кубика (0..1) — для напису "1 in 52K".
function GameMath.GetHeroChance(dice, heroId, playerLuck)
	local heroDef = HeroConfig.Heroes[heroId]
	if not heroDef then
		return 0
	end
	local weights, total = GameMath.GetRarityWeights(dice, playerLuck)
	if total <= 0 then
		return 0
	end
	local heroWeight, rarityTotal = 0, 0
	for _, other in HeroConfig.ByRarity[heroDef.rarity] or {} do
		local weight = if dice.element and other.element == dice.element then dice.elementBonus else 1
		rarityTotal += weight
		if other.id == heroId then
			heroWeight = weight
		end
	end
	if rarityTotal <= 0 then
		return 0
	end
	return weights[heroDef.rarity] / total * heroWeight / rarityTotal
end

-- 0.000019 -> "1 in 52.6K"
function GameMath.FormatOdds(chance)
	if chance <= 0 then
		return "1 in ∞"
	end
	return "1 in " .. GameMath.FormatNumber(math.max(1, math.floor(1 / chance + 0.5)))
end

function GameMath.GetIncomeMultiplier(incomeLevel)
	return 1 + (incomeLevel or 0) * EconomyConfig.IncomeUpgrade.bonusPerLevel
end

-- Множник пробудженої форми (1, якщо герой не пробуджений)
function GameMath.GetAwakenMultiplier(heroDef, awakened)
	return if awakened then heroDef.awakened.multiplier else 1
end

function GameMath.GetHeroIncome(heroDef, level, incomeLevel, awakened)
	local levelBonus = 1 + EconomyConfig.LevelIncomeBonus * (level - 1)
	return heroDef.income * levelBonus * GameMath.GetIncomeMultiplier(incomeLevel) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetHeroDamage(heroDef, level, awakened)
	return heroDef.damage * (1 + EconomyConfig.LevelDamageBonus * (level - 1)) * GameMath.GetAwakenMultiplier(heroDef, awakened)
end

function GameMath.GetSellPrice(heroDef, level)
	local base = RarityConfig.Info[heroDef.rarity].sellPrice
	return math.floor(base * (1 + EconomyConfig.SellLevelBonus * (level - 1)))
end

-- Ціна наступного слота або nil, якщо слотів уже максимум.
function GameMath.GetSlotPrice(slotCount)
	if slotCount >= EconomyConfig.MaxSlots then
		return nil
	end
	local upgrade = EconomyConfig.SlotUpgrade
	return math.floor(upgrade.basePrice * upgrade.growth ^ (slotCount - EconomyConfig.StartSlots))
end

-- Ціна наступного рівня доходу або nil, якщо досягнуто максимуму.
function GameMath.GetIncomeUpgradePrice(incomeLevel)
	local upgrade = EconomyConfig.IncomeUpgrade
	if incomeLevel >= upgrade.maxLevel then
		return nil
	end
	return math.floor(upgrade.basePrice * upgrade.growth ^ incomeLevel)
end

-- Номер доби UTC (для щоденних завдань).
function GameMath.GetDay(now)
	return math.floor(now / 86400)
end

-- Чи діє буст ("luck" / "income") у момент now. now = nil — бусти не враховуються.
function GameMath.IsBoostActive(data, boostId, now)
	return now ~= nil and (data.boosts[boostId] or 0) > now
end

function GameMath.GetBoostMultiplier(data, boostId, now)
	if GameMath.IsBoostActive(data, boostId, now) then
		return ShopConfig.Boosts[boostId].multiplier
	end
	return 1
end

-- Удача гравця (множиться на удачу кубика): зілля × бонус Rebirth.
function GameMath.GetLuck(data, now)
	return GameMath.GetBoostMultiplier(data, "luck", now) * GameMath.GetRebirthLuck(data.rebirths or 0)
end

function GameMath.GetHeroName(heroDef, awakened)
	return if awakened then heroDef.awakened.name else heroDef.name
end

-- Чи можна пробудити героя. Повертає ok, причина, ціна.
function GameMath.CanAwaken(heroDef, hero)
	local info = RarityConfig.Info[heroDef.rarity]
	if hero.awakened then
		return false, "Герой уже пробуджений", info.awakenCost
	end
	if hero.level < info.maxLevel then
		return false, ("Потрібен максимальний рівень %d (зараз %d)"):format(info.maxLevel, hero.level), info.awakenCost
	end
	return true, nil, info.awakenCost
end

-- Rebirth
function GameMath.GetRebirthCost(rebirths)
	local config = EconomyConfig.Rebirth
	return math.floor(config.baseCost * config.growth ^ rebirths)
end

function GameMath.GetRebirthIncome(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.incomeBonus
end

function GameMath.GetRebirthLuck(rebirths)
	return 1 + rebirths * EconomyConfig.Rebirth.luckBonus
end

function GameMath.CountDiscovered(data)
	local count = 0
	for heroId in data.discovered do
		if HeroConfig.Heroes[heroId] then
			count += 1
		end
	end
	return count
end

-- Бонус колекції: +2% доходу за кожного відкритого героя.
function GameMath.GetCollectionMultiplier(data)
	return 1 + GameMath.CountDiscovered(data) * EconomyConfig.CollectionIncomeBonus
end

function GameMath.GetMaxInventory(data)
	return EconomyConfig.MaxInventory + (data.inventoryBonus or 0)
end

-- Ціна наступної "Більшої сумки" або nil, якщо куплено максимум.
function GameMath.GetBagPrice(data)
	local item = ShopConfig.Items.BigBag
	local purchases = math.floor((data.inventoryBonus or 0) / item.amount)
	if purchases >= item.maxPurchases then
		return nil
	end
	return item.basePrice + item.priceStep * purchases
end

-- Скільки ворогів гравець переміг саме в цьому світі.
function GameMath.GetWorldKills(data, worldId)
	return data.worldKills[worldId] or 0
end

function GameMath.GetBossKills(data, enemyId)
	return data.bossKills[enemyId] or 0
end

function GameMath.GetEnemyName(enemyId)
	local def = EnemyConfig.Enemies[enemyId]
	return if def then def.name else tostring(enemyId)
end

-- Чи відкрита зона zoneIndex світу worldId (зони без вимог відкриті завжди).
function GameMath.IsZoneUnlocked(data, worldId, zoneIndex)
	local world = WorldConfig.Worlds[worldId]
	local zone = world and world.zones and world.zones[zoneIndex]
	if not zone then
		return true
	end
	return GameMath.GetWorldKills(data, worldId) >= zone.requiredKills
end

-- Чи можна потрапити у світ. Повертає ok, текст вимоги.
function GameMath.IsWorldUnlocked(data, worldId)
	local world = WorldConfig.Worlds[worldId]
	if not world or not world.available then
		return false, "Скоро"
	end
	local unlock = world.unlock
	if unlock and unlock.boss and GameMath.GetBossKills(data, unlock.boss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(unlock.boss)
	end
	return true, nil
end

-- Чи відкритий кубик. Повертає ok, текст вимоги.
function GameMath.IsDiceUnlocked(data, dice)
	if data.totalRolls < dice.requiredRolls then
		return false, ("%d / %d кидків"):format(data.totalRolls, dice.requiredRolls)
	end
	if dice.requiredBoss and GameMath.GetBossKills(data, dice.requiredBoss) < 1 then
		return false, "Переможи " .. GameMath.GetEnemyName(dice.requiredBoss)
	end
	return true, nil
end

-- Значення для сюжетних завдань (QuestConfig.Main[].metric).
function GameMath.GetMetric(data, metric)
	if metric == "totalRolls" then
		return data.totalRolls
	elseif metric == "slotCount" then
		return data.slotCount
	elseif metric == "discovered" then
		return GameMath.CountDiscovered(data)
	elseif metric == "placedHeroes" then
		local count = 0
		for i = 1, data.slotCount do
			if data.slots[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "teamSize" then
		local count = 0
		for i = 1, CombatConfig.TeamSize do
			if data.team[i] ~= "" then
				count += 1
			end
		end
		return count
	elseif metric == "rebirths" then
		return data.rebirths or 0
	elseif metric == "awakenedHeroes" then
		local count = 0
		for _, hero in data.heroes do
			if hero.awakened then
				count += 1
			end
		end
		return count
	elseif metric == "maxHeroLevel" then
		local best = 0
		for _, hero in data.heroes do
			best = math.max(best, hero.level)
		end
		return best
	elseif string.sub(metric, 1, 6) == "kills:" then
		return GameMath.GetWorldKills(data, string.sub(metric, 7))
	elseif string.sub(metric, 1, 5) == "boss:" then
		return GameMath.GetBossKills(data, string.sub(metric, 6))
	elseif data.stats[metric] ~= nil then
		return data.stats[metric]
	end
	return 0
end

-- "+300 🪙 +1 💎"
function GameMath.FormatReward(reward)
	local parts = {}
	if reward.coins and reward.coins > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.coins) .. " 🪙")
	end
	if reward.crystals and reward.crystals > 0 then
		table.insert(parts, "+" .. GameMath.FormatNumber(reward.crystals) .. " 💎")
	end
	return table.concat(parts, " ")
end

-- 125 -> "2:05"
function GameMath.FormatTime(seconds)
	seconds = math.max(0, math.floor(seconds))
	if seconds >= 3600 then
		return string.format("%d:%02d:%02d", seconds // 3600, (seconds % 3600) // 60, seconds % 60)
	end
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

-- Загальний дохід бази за секунду з бонусом колекції.
-- now — серверний час; якщо передано, враховується буст доходу.
function GameMath.GetTotalIncome(data, now)
	local total = 0
	for i = 1, data.slotCount do
		local uid = data.slots[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroIncome(heroDef, hero.level, data.incomeLevel, hero.awakened)
		end
	end
	return total
		* GameMath.GetCollectionMultiplier(data)
		* GameMath.GetRebirthIncome(data.rebirths or 0)
		* GameMath.GetBoostMultiplier(data, "income", now)
end

-- Шкода героя за секунду.
function GameMath.GetHeroDps(heroDef, level, awakened)
	return GameMath.GetHeroDamage(heroDef, level, awakened) * heroDef.attackSpeed
end

-- Чи входить герой до бойової команди.
function GameMath.IsInTeam(data, uid)
	for i = 1, CombatConfig.TeamSize do
		if data.team[i] == uid then
			return true
		end
	end
	return false
end

-- Чи стоїть герой на базі.
function GameMath.IsOnBase(data, uid)
	for i = 1, data.slotCount do
		if data.slots[i] == uid then
			return true
		end
	end
	return false
end

-- Сумарна шкода команди за секунду.
function GameMath.GetTeamDps(data)
	local total = 0
	for i = 1, CombatConfig.TeamSize do
		local uid = data.team[i]
		local hero = uid and uid ~= "" and data.heroes[uid]
		local heroDef = hero and HeroConfig.Heroes[hero.id]
		if heroDef then
			total += GameMath.GetHeroDps(heroDef, hero.level, hero.awakened)
		end
	end
	return total
end

-- Скільки кидків лишилось до гарантії кожного рівня.
function GameMath.GetPityRemaining(data)
	local result = {}
	for _, tier in EconomyConfig.Pity do
		local count = data.pity[tier.rarity] or 0
		table.insert(result, { rarity = tier.rarity, remaining = math.max(tier.rolls - count, 1) })
	end
	return result
end

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi" }

-- 1234 -> "1.23K", 5600000 -> "5.6M"
function GameMath.FormatNumber(value)
	value = tonumber(value) or 0
	if math.abs(value) < 1000 then
		if value == math.floor(value) then
			return tostring(value)
		end
		return string.format("%.1f", value)
	end
	local index = 1
	while math.abs(value) >= 1000 and index < #SUFFIXES do
		value /= 1000
		index += 1
	end
	local text = string.format("%.2f", value):gsub("%.?0+$", "")
	return text .. SUFFIXES[index]
end

function GameMath.FormatChance(percent)
	if percent <= 0 then
		return "—"
	elseif percent < 0.01 then
		return "<0.01%"
	elseif percent < 1 then
		return string.format("%.2f%%", percent)
	end
	return string.format("%.1f%%", percent)
end

return GameMath
