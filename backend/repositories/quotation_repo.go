package repositories

import (
	"errors"
	"time"

	"github.com/cshliu/ezstore/backend/models"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type QuotationRepository struct {
	DB *gorm.DB
}

func NewQuotationRepository(db *gorm.DB) *QuotationRepository {
	return &QuotationRepository{DB: db}
}

func (r *QuotationRepository) List(page, pageSize int, status string, customerID uint, quotationNumber string) ([]models.Quotation, int64, error) {
	var quotations []models.Quotation
	var total int64

	query := r.DB.Model(&models.Quotation{})
	if status != "" {
		query = query.Where("status = ?", status)
	}
	if customerID > 0 {
		query = query.Where("customer_id = ?", customerID)
	}
	if quotationNumber != "" {
		query = query.Where("quotation_number = ?", quotationNumber)
	}

	if err := query.Count(&total).Error; err != nil {
		return nil, 0, err
	}

	offset := (page - 1) * pageSize
	if err := query.Preload("Customer").Preload("Items").Offset(offset).Limit(pageSize).Order("id DESC").Find(&quotations).Error; err != nil {
		return nil, 0, err
	}

	return quotations, total, nil
}

func (r *QuotationRepository) GetByID(id uint) (*models.Quotation, error) {
	var quotation models.Quotation
	if err := r.DB.Preload("Customer").Preload("Items").First(&quotation, id).Error; err != nil {
		return nil, err
	}
	return &quotation, nil
}

func (r *QuotationRepository) Create(quotation *models.Quotation) error {
	return r.DB.Create(quotation).Error
}

func (r *QuotationRepository) Update(quotation *models.Quotation) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		// Serialize with publishing before checking the current status. The service
		// may have read a draft that was published while this request waited.
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, quotation.ID).Error; err != nil {
			return err
		}
		if current.Status != "draft" {
			return errors.New("已發佈的報價單不可修改")
		}
		// Order creation/link changes take this same quotation lock and recheck
		// ownership. Thus a concurrent order cannot appear after this check.
		if current.CustomerID != quotation.CustomerID {
			var linked int64
			if err := tx.Model(&models.Order{}).Where("quotation_id = ?", quotation.ID).Count(&linked).Error; err != nil {
				return err
			}
			if linked > 0 {
				return errors.New("報價單已關聯訂單，不可更換客戶，請另建報價單")
			}
		}
		// Hard delete existing items (items don't use soft delete)
		if err := tx.Unscoped().Where("quotation_id = ?", quotation.ID).Delete(&models.QuotationItem{}).Error; err != nil {
			return err
		}
		// Save quotation with new items
		// Customer was preloaded before its FK was changed. Never save that stale association.
		return tx.Omit("Customer", "Status").Save(quotation).Error
	})
}

func (r *QuotationRepository) UpdateStatus(id uint, status string) error {
	return r.DB.Model(&models.Quotation{}).Where("id = ?", id).Update("status", status).Error
}

func (r *QuotationRepository) Delete(id uint) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, id).Error; err != nil {
			return err
		}
		if current.Status != "draft" {
			return errors.New("已發佈的報價單不可刪除")
		}
		// Order creation/relinking takes the same quotation lock. Check after
		// acquiring it so a just-committed order cannot lose its source quote.
		var linked int64
		if err := tx.Model(&models.Order{}).Where("quotation_id = ?", id).Count(&linked).Error; err != nil {
			return err
		}
		if linked > 0 {
			return errors.New("報價單已關聯訂單，不可刪除")
		}
		return tx.Delete(&current).Error
	})
}

// Failure compensation may remove only the exact draft version the MCP saw.
// Do not discard another user's edit, a published quote, or a converted quote.
func (r *QuotationRepository) DeleteDraftIfUnchanged(id uint, expected time.Time) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		// Order creation and relinking acquire this same lock. Acquire it in a
		// separate statement so the following NOT EXISTS uses a fresh snapshot
		// after any order transaction we waited for has committed.
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, id).Error; err != nil {
			return err
		}
		result := tx.Where("id = ? AND status = ? AND updated_at = ?", id, "draft", expected).
			Where("NOT EXISTS (SELECT 1 FROM orders WHERE orders.quotation_id = quotations.id AND orders.deleted_at IS NULL)").
			Delete(&models.Quotation{})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return errors.New("副本已變更、已轉訂單或已不存在，未自動刪除")
		}
		return nil
	})
}

func (r *QuotationRepository) CountForDate(date string) (int64, error) {
	var count int64
	// Count by the same business-date prefix used to assign numbers, including
	// soft-deleted rows. Database timezone and imported created_at values do not apply.
	err := r.DB.Unscoped().Model(&models.Quotation{}).
		Where("quotation_number LIKE ?", "QT-"+date+"-%").
		Count(&count).Error
	return count, err
}
