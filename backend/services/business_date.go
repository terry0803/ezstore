package services

import "time"

// Taiwan business dates must not depend on the container or database timezone.
// Modern Taiwan uses UTC+8 without daylight saving; no OS tzdata is required.
var taipei = time.FixedZone("Asia/Taipei", 8*60*60)

func businessDate(now time.Time) string {
	return now.In(taipei).Format("20060102")
}
