-- RateLimiter: обмеження частоти запитів (алгоритм "відро з жетонами").
-- RateLimiter.new(4, 2) — до 4 запитів одразу, далі 2 запити на секунду.

local RateLimiter = {}
RateLimiter.__index = RateLimiter

function RateLimiter.new(maxTokens, refillPerSecond)
	local self = setmetatable({}, RateLimiter)
	self.maxTokens = maxTokens
	self.refillPerSecond = refillPerSecond
	-- Слабкі ключі: коли гравець виходить, його запис зникає сам.
	self.buckets = setmetatable({}, { __mode = "k" })
	return self
end

-- true — запит дозволено, false — забагато запитів.
function RateLimiter:Check(player)
	local now = os.clock()
	local bucket = self.buckets[player]
	if not bucket then
		bucket = { tokens = self.maxTokens, last = now }
		self.buckets[player] = bucket
	end
	bucket.tokens = math.min(self.maxTokens, bucket.tokens + (now - bucket.last) * self.refillPerSecond)
	bucket.last = now
	if bucket.tokens >= 1 then
		bucket.tokens -= 1
		return true
	end
	return false
end

return RateLimiter
