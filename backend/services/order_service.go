package services

import (
	"errors"
	"fmt"
	"time"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/cshliu/ezstore/backend/repositories"
	"github.com/shopspring/decimal"
)

type OrderCreateInput struct {
	CustomerID  uint             `json:"customer_id" binding:"required"`
	QuotationID *uint            `json:"quotation_id"`
	Notes       string           `json:"notes"`
	Items       []OrderItemInput `json:"items" binding:"required,min=1"`
}

type OrderItemInput struct {
	ProductID uint            `json:"product_id" binding:"required"`
	UnitPrice decimal.Decimal `json:"unit_price" binding:"required"`
	Quantity  int             `json:"quantity" binding:"required,min=1"`
}

type OrderService struct {
	Repo         *repositories.OrderRepository
	CustomerRepo *repositories.CustomerRepository
	ProductRepo  *repositories.ProductRepository
	// Reads the linked quotation so an order cannot point at another customer's quotation.
	QuotationRepo quotationLookup
}

type quotationLookup interface {
	GetByID(id uint) (*models.Quotation, error)
}

func NewOrderService(repo *repositories.OrderRepository, customerRepo *repositories.CustomerRepository, productRepo *repositories.ProductRepository) *OrderService {
	service := &OrderService{Repo: repo, CustomerRepo: customerRepo, ProductRepo: productRepo}
	if repo != nil {
		service.QuotationRepo = repositories.NewQuotationRepository(repo.DB)
	}
	return service
}

func (s *OrderService) List(page, pageSize int, status string, customerID uint) ([]models.Order, int64, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	return s.Repo.List(page, pageSize, status, customerID)
}

func (s *OrderService) GetByID(id uint) (*models.Order, error) {
	return s.Repo.GetByID(id)
}

func (s *OrderService) Create(input *OrderCreateInput) (*models.Order, error) {
	if err := validateOrderInput(input); err != nil {
		return nil, err
	}
	if err := s.validateQuotation(input); err != nil {
		return nil, err
	}
	if _, err := s.CustomerRepo.GetByID(input.CustomerID); err != nil {
		return nil, errors.New("客戶不存在")
	}

	order := &models.Order{
		CustomerID:  input.CustomerID,
		QuotationID: input.QuotationID,
		Status:      "pending",
		Notes:       input.Notes,
	}

	items, err := s.buildItems(input.Items)
	if err != nil {
		return nil, err
	}
	order.Items = items

	totalPrice := decimal.Zero
	for _, item := range items {
		totalPrice = totalPrice.Add(item.Subtotal)
	}
	order.TotalPrice = totalPrice

	if err := createWithRetry(s.generateNumber, func(n string) { order.OrderNumber = n }, func() error { return s.Repo.Create(order) }); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(order.ID)
}

func (s *OrderService) Update(id uint, input *OrderCreateInput) (*models.Order, error) {
	if err := validateOrderInput(input); err != nil {
		return nil, err
	}
	if err := s.validateQuotation(input); err != nil {
		return nil, err
	}
	existing, err := s.Repo.GetByID(id)
	if err != nil {
		return nil, err
	}

	if _, err := s.CustomerRepo.GetByID(input.CustomerID); err != nil {
		return nil, errors.New("客戶不存在")
	}

	existing.CustomerID = input.CustomerID
	existing.QuotationID = input.QuotationID
	existing.Notes = input.Notes

	items, err := s.buildItems(input.Items)
	if err != nil {
		return nil, err
	}
	existing.Items = items

	totalPrice := decimal.Zero
	for _, item := range items {
		totalPrice = totalPrice.Add(item.Subtotal)
	}
	existing.TotalPrice = totalPrice

	if err := s.Repo.Update(existing); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(existing.ID)
}

// Reject negative prices before any database access (an order total of -2 was accepted).
func validateOrderInput(input *OrderCreateInput) error {
	if input == nil || len(input.Items) == 0 {
		return errors.New("訂單至少需要一個品項")
	}
	for _, item := range input.Items {
		if item.UnitPrice.IsNegative() {
			return errors.New("訂單單價不可為負數")
		}
		if item.Quantity <= 0 {
			return errors.New("數量必須大於 0")
		}
	}
	return nil
}

func (s *OrderService) validateQuotation(input *OrderCreateInput) error {
	if input.QuotationID == nil {
		return nil
	}
	if s.QuotationRepo == nil {
		return errors.New("無法驗證關聯報價單")
	}
	quotation, err := s.QuotationRepo.GetByID(*input.QuotationID)
	if err != nil || quotation == nil {
		return errors.New("關聯報價單不存在")
	}
	if quotation.CustomerID != input.CustomerID {
		return errors.New("關聯報價單與訂單必須屬於同一客戶")
	}
	return nil
}

func (s *OrderService) Delete(id uint) error {
	return s.Repo.Delete(id)
}

func (s *OrderService) buildItems(inputs []OrderItemInput) ([]models.OrderItem, error) {
	items := make([]models.OrderItem, 0, len(inputs))

	for _, input := range inputs {
		product, err := s.ProductRepo.GetByID(input.ProductID)
		if err != nil {
			return nil, fmt.Errorf("產品 ID %d 不存在", input.ProductID)
		}

		if input.Quantity <= 0 {
			return nil, errors.New("數量必須大於 0")
		}

		quantity := decimal.NewFromInt(int64(input.Quantity))
		unitPrice := input.UnitPrice.Round(2)
		subtotal := unitPrice.Mul(quantity)

		items = append(items, models.OrderItem{
			ProductID:   input.ProductID,
			ProductName: product.Name,
			UnitPrice:   unitPrice,
			Quantity:    input.Quantity,
			Subtotal:    subtotal,
		})
	}

	return items, nil
}

// generateNumber 產生 ORD-YYYYMMDD-NNN；offset 用於撞號重試時往後推序號。
func (s *OrderService) generateNumber(offset int64) (string, error) {
	count, err := s.Repo.CountToday()
	if err != nil {
		return "", err
	}
	today := time.Now().Format("20060102")
	return fmt.Sprintf("ORD-%s-%03d", today, count+1+offset), nil
}
