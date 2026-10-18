package services

// NormalizePagination is shared by handlers (response metadata) and services.
func NormalizePagination(page, pageSize int) (int, int) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	// Avoid an overflowing SQL offset from a syntactically valid huge page.
	if page-1 > int(^uint(0)>>1)/pageSize {
		page = 1
	}
	return page, pageSize
}
