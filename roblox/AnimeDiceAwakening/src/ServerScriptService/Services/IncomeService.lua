-- IncomeService: нарахування монет від героїв на базі та офлайн-дохід.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local EconomyConfig = require(Shared.Config.EconomyConfig)
local GameMath = require(Shared.GameMath)
local Remotes = require(Shared.Remotes)

local DataService = require(script.Parent.DataService)

local IncomeService = {}

-- Офлайн-дохід за серверним часом (os.time — UTC на сервері Roblox).
function IncomeService.GrantOfflineIncome(player)
	local data = DataService.Get(player)
	if not data or data.lastSeen <= 0 then
		return
	end
	local elapsed = math.clamp(os.time() - data.lastSeen, 0, EconomyConfig.OfflineMaxSeconds)
	-- Бусти офлайн не діють (GetTotalIncome без часу), бонус колекції — діє
	local amount = math.floor(GameMath.GetTotalIncome(data) * elapsed * EconomyConfig.OfflineRate)
	data.lastSeen = os.time() -- не дати нарахувати двічі
	if amount > 0 then
		DataService.AddCoins(player, amount)
		local minutes = math.floor(elapsed / 60)
		Remotes.Notify(player, ("Поки тебе не було (%d хв), герої заробили %s монет!"):format(minutes, GameMath.FormatNumber(amount)), "success")
	end
end

function IncomeService.Init()
	task.spawn(function()
		local last = os.clock()
		while true do
			task.wait(EconomyConfig.IncomeTickSeconds)
			local now = os.clock()
			local dt = math.min(now - last, 5)
			last = now
			for _, player in Players:GetPlayers() do
				local profile = DataService.GetProfile(player)
				if profile then
					-- Дробові монети накопичуються й нараховуються, коли набереться ціла.
					profile.incomeRemainder += GameMath.GetTotalIncome(profile.data, os.time()) * dt
					local whole = math.floor(profile.incomeRemainder)
					if whole > 0 then
						profile.incomeRemainder -= whole
						DataService.AddCoins(player, whole)
					end
				end
			end
		end
	end)
end

return IncomeService
