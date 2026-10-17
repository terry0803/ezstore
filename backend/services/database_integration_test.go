package services

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/cshliu/ezstore/backend/repositories"
	"github.com/shopspring/decimal"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// These tests never use ConnectDatabase or the application's .env. The runner
// must explicitly supply a disposable PostgreSQL database named ezstore_recheck.
func integrationDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := os.Getenv("EZSTORE_INTEGRATION_DSN")
	if dsn == "" {
		t.Skip("requires explicitly configured disposable PostgreSQL")
	}
	require.Contains(t, " "+dsn+" ", " dbname=ezstore_recheck ")
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	var database string
	require.NoError(t, db.Raw("SELECT current_database()").Scan(&database).Error)
	require.Equal(t, "ezstore_recheck", database)
	schema := fmt.Sprintf("regression_%d", time.Now().UnixNano())
	require.NoError(t, db.Exec("CREATE SCHEMA "+schema).Error)
	schemaDB, err := gorm.Open(postgres.Open(dsn+" search_path="+schema), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := schemaDB.DB()
		_ = sqlDB.Close()
		_ = db.Exec("DROP SCHEMA " + schema + " CASCADE").Error
		adminDB, _ := db.DB()
		_ = adminDB.Close()
	})
	require.NoError(t, schemaDB.AutoMigrate(&models.Customer{}, &models.Product{}, &models.Quotation{}, &models.QuotationItem{}, &models.Order{}, &models.OrderItem{}))
	require.NoError(t, schemaDB.Create(&models.Customer{ID: 1, Name: "Original", TaxID: "11111111", Level: "standard"}).Error)
	require.NoError(t, schemaDB.Create(&models.Customer{ID: 2, Name: "Replacement", TaxID: "22222222", Level: "vip"}).Error)
	require.NoError(t, schemaDB.Create(&models.Product{ID: 1, ProductNumber: "P-TEST", Name: "Test product", Cost: decimal.NewFromInt(40), ListPrice: decimal.NewFromInt(100)}).Error)
	return schemaDB
}

func integrationServices(db *gorm.DB) (*QuotationService, *OrderService) {
	c := repositories.NewCustomerRepository(db)
	p := repositories.NewProductRepository(db)
	return NewQuotationService(repositories.NewQuotationRepository(db), c, p), NewOrderService(repositories.NewOrderRepository(db), c, p)
}

func quotationInput(customerID uint, quantity int) *QuotationCreateInput {
	return &QuotationCreateInput{CustomerID: customerID, PricingFactor: decimal.NewFromInt(1), Items: []QuotationItemInput{{ProductID: 1, Quantity: quantity}}}
}

func orderInput(customerID uint, quantity int) *OrderCreateInput {
	return &OrderCreateInput{CustomerID: customerID, Items: []OrderItemInput{{ProductID: 1, UnitPrice: decimal.NewFromInt(100), Quantity: quantity}}}
}

func TestDatabaseQuotationCustomerUpdate(t *testing.T) {
	q, _ := integrationServices(integrationDB(t))
	original, err := q.Create(quotationInput(1, 1))
	require.NoError(t, err)
	updated, err := q.Update(original.ID, quotationInput(2, 2))
	require.NoError(t, err)
	require.Equal(t, uint(2), updated.CustomerID, "loaded old Customer must not overwrite the explicitly requested foreign key")
	require.Equal(t, "Replacement", updated.Customer.Name)
	require.Equal(t, "vip", updated.CustomerLevel)
	stored, err := q.GetByID(original.ID)
	require.NoError(t, err)
	require.Equal(t, updated.CustomerID, stored.CustomerID)
	require.Len(t, stored.Items, 1)
}

func TestDatabaseOrderCustomerUpdate(t *testing.T) {
	_, o := integrationServices(integrationDB(t))
	original, err := o.Create(orderInput(1, 1))
	require.NoError(t, err)
	updated, err := o.Update(original.ID, orderInput(2, 2))
	require.NoError(t, err)
	require.Equal(t, uint(2), updated.CustomerID, "saving a preloaded Customer must not undo the customer's change")
	require.Equal(t, "Replacement", updated.Customer.Name)
}

// A short trigger makes overlapping writes reproducible instead of relying on
// goroutine timing. It exists only in this test's disposable schema.
func slowParentUpdates(t *testing.T, db *gorm.DB, table string) {
	t.Helper()
	require.Contains(t, []string{"quotations", "orders"}, table)
	require.NoError(t, db.Exec(`CREATE FUNCTION slow_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.15); RETURN NEW; END $$`).Error)
	require.NoError(t, db.Exec("CREATE TRIGGER slow_update BEFORE UPDATE ON "+table+" FOR EACH ROW EXECUTE FUNCTION slow_update()").Error)
}

func parallelWrites(t *testing.T, write func(int) error) {
	t.Helper()
	var wg sync.WaitGroup
	start := make(chan struct{})
	errors := make(chan error, 2)
	for _, quantity := range []int{2, 3} {
		wg.Add(1)
		go func(quantity int) {
			defer wg.Done()
			<-start
			errors <- write(quantity)
		}(quantity)
	}
	close(start)
	wg.Wait()
	close(errors)
	for err := range errors {
		require.NoError(t, err)
	}
}

func TestDatabaseConcurrentQuotationUpdatesReplaceItems(t *testing.T) {
	db := integrationDB(t)
	q, _ := integrationServices(db)
	original, err := q.Create(quotationInput(1, 1))
	require.NoError(t, err)
	slowParentUpdates(t, db, "quotations")
	parallelWrites(t, func(quantity int) error {
		_, err := q.Update(original.ID, quotationInput(1, quantity))
		return err
	})
	stored, err := q.GetByID(original.ID)
	require.NoError(t, err)
	require.Len(t, stored.Items, 1, "concurrent replacements must not merge item lists")
	require.True(t, stored.TotalPrice.Equal(stored.Items[0].Subtotal), "header total and stored items must agree")
}

func TestDatabaseConcurrentOrderUpdatesReplaceItems(t *testing.T) {
	db := integrationDB(t)
	_, o := integrationServices(db)
	original, err := o.Create(orderInput(1, 1))
	require.NoError(t, err)
	slowParentUpdates(t, db, "orders")
	parallelWrites(t, func(quantity int) error {
		_, err := o.Update(original.ID, orderInput(1, quantity))
		return err
	})
	stored, err := o.GetByID(original.ID)
	require.NoError(t, err)
	require.Len(t, stored.Items, 1, "concurrent replacements must not merge item lists")
	require.True(t, stored.TotalPrice.Equal(stored.Items[0].Subtotal))
}

func TestDatabaseStaleDraftCannotUndoPublish(t *testing.T) {
	db := integrationDB(t)
	q, _ := integrationServices(db)
	original, err := q.Create(quotationInput(1, 1))
	require.NoError(t, err)
	// Equivalent to an edit request which loaded the draft before another
	// request published it, then reached its write after that publication.
	stale, err := q.GetByID(original.ID)
	require.NoError(t, err)
	_, err = q.Publish(original.ID)
	require.NoError(t, err)
	stale.Notes = "late edit"
	err = q.Repo.Update(stale)
	require.Error(t, err, "a stale draft must not overwrite a published quotation")
	stored, err := q.GetByID(original.ID)
	require.NoError(t, err)
	require.Equal(t, "published", stored.Status)
	require.NotEqual(t, "late edit", stored.Notes)
}

func TestDatabaseStaleDraftCannotDeleteAfterPublish(t *testing.T) {
	db := integrationDB(t)
	q, _ := integrationServices(db)
	original, err := q.Create(quotationInput(1, 1))
	require.NoError(t, err)
	_, err = q.Publish(original.ID)
	require.NoError(t, err)
	// A delete request may have passed the service's draft check before
	// publication; the repository must check again while holding its lock.
	require.Error(t, q.Repo.Delete(original.ID))
	stored, err := q.GetByID(original.ID)
	require.NoError(t, err)
	require.Equal(t, "published", stored.Status)
}

func TestDatabaseRepeatedConversionRemainsAllowed(t *testing.T) {
	db := integrationDB(t)
	q, o := integrationServices(db)
	original, err := q.Create(quotationInput(1, 1))
	require.NoError(t, err)
	parallelWrites(t, func(_ int) error {
		input := orderInput(1, 1)
		input.QuotationID = &original.ID
		_, err := o.Create(input)
		return err
	})
	orders, total, err := o.List(1, 100, "", 1)
	require.NoError(t, err)
	require.EqualValues(t, 2, total, "the first Agent contract permits repeated conversion")
	require.NotEqual(t, orders[0].OrderNumber, orders[1].OrderNumber)
	for _, order := range orders {
		require.Equal(t, original.ID, *order.QuotationID)
		require.True(t, strings.HasPrefix(order.OrderNumber, "ORD-"))
	}
}

func TestDatabaseStoredFactorMatchesItemPrices(t *testing.T) {
	q, _ := integrationServices(integrationDB(t))
	input := quotationInput(1, 3)
	input.PricingFactor = decimal.RequireFromString("0.77515")
	created, err := q.Create(input)
	require.NoError(t, err)
	stored, err := q.GetByID(created.ID)
	require.NoError(t, err)
	require.Equal(t, "0.7752", stored.PricingFactor.StringFixed(4))
	require.Len(t, stored.Items, 1)
	// 單價 = 定價 100 x 存進去的因子 0.7752，總價 = 單價 x 3
	require.Equal(t, "77.52", stored.Items[0].UnitPrice.StringFixed(2))
	require.Equal(t, "232.56", stored.TotalPrice.StringFixed(2))

	input.PricingFactor = decimal.RequireFromString("10")
	_, err = q.Update(created.ID, input)
	require.EqualError(t, err, "報價因子不可超過 9.9999")
	input.PricingFactor = decimal.RequireFromString("0.01")
	_, err = q.Update(created.ID, input)
	require.EqualError(t, err, "報價因子太低，利潤率超出可儲存的範圍（-9.9999 到 9.9999）")
}
