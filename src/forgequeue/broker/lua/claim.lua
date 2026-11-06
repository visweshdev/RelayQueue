-- KEYS ready0,ready1,ready2,leases,worker_claim_count; ARGV lease_ms,token
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + tonumber(t[2]) / 1000
local count = tonumber(redis.call('GET', KEYS[5]) or '0')
local order = {1,2,3}
if (count + 1) % 10 == 0 then order = {3,2,1} end
for _, i in ipairs(order) do
  for n = 1, 32 do
    local item = redis.call('ZPOPMIN', KEYS[i], 1)
    if not item[1] then break end
    local id = item[1]
    -- Reconciliation must never turn a live lease into a second valid claim.
    if redis.call('EXISTS', 'fq:lease:' .. id) == 0 then
      redis.call('SET', 'fq:lease:' .. id, ARGV[2], 'PX', ARGV[1])
      redis.call('ZADD', KEYS[4], now + tonumber(ARGV[1]), id)
      redis.call('SET', KEYS[5], count + 1, 'EX', 86400)
      return id
    end
  end
end
return false
