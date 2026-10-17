package repositories

import (
	"errors"

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
		// Serialize the complete replacement, including deletion of old items.
		// Locking only when Save updates the header is too late: two deletes
		// can share an old snapshot and leave both replacement item lists.
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, quotation.ID).Error; err != nil {
			return err
		}
		if current.Status == "published" {
			return errors.New("已發佈的報價單不可修改")
		}
		// Hard delete existing items (items don't use soft delete)
		if err := tx.Unscoped().Where("quotation_id = ?", quotation.ID).Delete(&models.QuotationItem{}).Error; err != nil {
			return err
		}
		// Save quotation with new items
		// Customer is a preloaded read snapshot. Saving it would replace the
		// requested CustomerID with that snapshot's old ID.
		return tx.Omit("Customer").Save(quotation).Error
	})
}

func (r *QuotationRepository) UpdateStatus(id uint, status string) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, id).Error; err != nil {
			return err
		}
		if current.Status == "published" {
			return errors.New("報價單已經發佈")
		}
		return tx.Model(&current).Update("status", status).Error
	})
}

func (r *QuotationRepository) Delete(id uint) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		var current models.Quotation
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, id).Error; err != nil {
			return err
		}
		if current.Status == "published" {
			return errors.New("已發佈的報價單不可刪除")
		}
		return tx.Delete(&current).Error
	})
}

func (r *QuotationRepository) CountToday() (int64, error) {
	var count int64
	// 含已軟刪除的資料：單號的唯一索引包含它們，不算進去會撞號
	err := r.DB.Unscoped().Model(&models.Quotation{}).
		Where("DATE(created_at) = CURRENT_DATE").
		Count(&count).Error
	return count, err
}
