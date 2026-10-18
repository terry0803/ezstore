package repositories

import (
	"errors"
	"github.com/cshliu/ezstore/backend/models"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type OrderRepository struct {
	DB *gorm.DB
}

func NewOrderRepository(db *gorm.DB) *OrderRepository {
	return &OrderRepository{DB: db}
}

func (r *OrderRepository) List(page, pageSize int, status string, customerID uint) ([]models.Order, int64, error) {
	var orders []models.Order
	var total int64

	query := r.DB.Model(&models.Order{})
	if status != "" {
		query = query.Where("status = ?", status)
	}
	if customerID > 0 {
		query = query.Where("customer_id = ?", customerID)
	}

	if err := query.Count(&total).Error; err != nil {
		return nil, 0, err
	}

	offset := (page - 1) * pageSize
	if err := query.Preload("Customer").Preload("Items").Offset(offset).Limit(pageSize).Order("id DESC").Find(&orders).Error; err != nil {
		return nil, 0, err
	}

	return orders, total, nil
}

func (r *OrderRepository) GetByID(id uint) (*models.Order, error) {
	var order models.Order
	if err := r.DB.Preload("Customer").Preload("Items").First(&order, id).Error; err != nil {
		return nil, err
	}
	return &order, nil
}

func (r *OrderRepository) Create(order *models.Order) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		if err := lockOrderQuotation(tx, order); err != nil {
			return err
		}
		return tx.Create(order).Error
	})
}

func (r *OrderRepository) Update(order *models.Order) error {
	return r.DB.Transaction(func(tx *gorm.DB) error {
		// Lock the parent before replacing items, so concurrent updates cannot
		// delete the same old snapshot and then append both replacement sets.
		var current models.Order
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&current, order.ID).Error; err != nil {
			return err
		}
		if err := lockOrderQuotation(tx, order); err != nil {
			return err
		}
		if err := tx.Unscoped().Where("order_id = ?", order.ID).Delete(&models.OrderItem{}).Error; err != nil {
			return err
		}
		// Preserve the requested CustomerID instead of saving the preloaded old Customer.
		return tx.Omit("Customer", "Status").Save(order).Error
	})
}

func (r *OrderRepository) Delete(id uint) error {
	return r.DB.Delete(&models.Order{}, id).Error
}

func (r *OrderRepository) CountForDate(date string) (int64, error) {
	var count int64
	// Count by the same business-date prefix used to assign numbers, including
	// soft-deleted rows. Database timezone and imported created_at values do not apply.
	err := r.DB.Unscoped().Model(&models.Order{}).
		Where("order_number LIKE ?", "ORD-"+date+"-%").
		Count(&count).Error
	return count, err
}

// Revalidate under the same quotation row lock used by customer reassignment.
// The earlier service validation alone can become stale while a request waits.
func lockOrderQuotation(tx *gorm.DB, order *models.Order) error {
	if order.QuotationID == nil {
		return nil
	}
	var quotation models.Quotation
	if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&quotation, *order.QuotationID).Error; err != nil {
		return errors.New("關聯報價單不存在")
	}
	if quotation.CustomerID != order.CustomerID {
		return errors.New("關聯報價單與訂單必須屬於同一客戶")
	}
	return nil
}
