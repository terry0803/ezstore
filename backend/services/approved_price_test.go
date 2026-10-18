package services

import (
	"errors"
	"fmt"
	"os"
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

func approvalFixture(t *testing.T) (*gorm.DB, *QuotationService, ApprovedPriceInput) {
	t.Helper()
	dsn := os.Getenv("APPROVAL_TEST_DSN")
	if dsn == "" {
		t.Skip("set APPROVAL_TEST_DSN to an isolated PostgreSQL database")
	}
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	t.Cleanup(func() { sqlDB.Close() })
	require.NoError(t, db.AutoMigrate(&models.Customer{}, &models.Product{}, &models.Quotation{}, &models.QuotationItem{}))
	key := fmt.Sprint(time.Now().UnixNano())
	c := models.Customer{Name: "approval test", TaxID: key, Level: "standard"}
	p := models.Product{Name: "approval test", ProductNumber: key, Cost: decimal.NewFromInt(60), ListPrice: decimal.NewFromInt(100)}
	require.NoError(t, db.Create(&c).Error)
	require.NoError(t, db.Create(&p).Error)
	s := NewQuotationService(repositories.NewQuotationRepository(db), repositories.NewCustomerRepository(db), repositories.NewProductRepository(db))
	q, err := s.Create(&QuotationCreateInput{CustomerID: c.ID, PricingFactor: decimal.NewFromInt(1), Items: []QuotationItemInput{{ProductID: p.ID, Quantity: 1}}})
	require.NoError(t, err)
	return db, s, ApprovedPriceInput{Source: *q, Target: decimal.NewFromInt(100), Factor: decimal.NewFromInt(1), Total: decimal.NewFromInt(100), Profit: decimal.NewFromInt(40)}
}

func quoteCount(t *testing.T, db *gorm.DB) int64 {
	t.Helper()
	var n int64
	require.NoError(t, db.Unscoped().Model(&models.Quotation{}).Count(&n).Error)
	return n
}

func TestApprovedPriceCopyAtomicSuccess(t *testing.T) {
	db, s, input := approvalFixture(t)
	n := quoteCount(t, db)
	q, err := s.ApprovedPriceCopy(input.Source.ID, &input)
	require.NoError(t, err)
	require.Equal(t, n+1, quoteCount(t, db))
	require.NotEqual(t, input.Source.ID, q.ID)
	require.True(t, q.TotalPrice.Equal(input.Total))
	require.True(t, q.ProfitAmount.Equal(input.Profit))
	require.Equal(t, "draft", q.Status)
	original, err := s.GetByID(input.Source.ID)
	require.NoError(t, err)
	require.True(t, sameApprovedSource(original, &input.Source))
}

func TestApprovedPriceStaleDataLeavesNoDraft(t *testing.T) {
	for _, field := range []string{"quantity", "customer", "cost", "price", "deleted", "result", "factor", "version"} {
		t.Run(field, func(t *testing.T) {
			db, s, input := approvalFixture(t)
			switch field {
			case "quantity":
				_, err := s.Update(input.Source.ID, &QuotationCreateInput{CustomerID: input.Source.CustomerID, PricingFactor: input.Source.PricingFactor, Items: []QuotationItemInput{{ProductID: input.Source.Items[0].ProductID, Quantity: 2}}})
				require.NoError(t, err)
			case "customer":
				require.NoError(t, db.Model(&models.Customer{}).Where("id = ?", input.Source.CustomerID).Update("level", "new").Error)
			case "cost":
				require.NoError(t, db.Model(&models.Product{}).Where("id = ?", input.Source.Items[0].ProductID).Update("cost", 120).Error)
			case "price":
				require.NoError(t, db.Model(&models.Product{}).Where("id = ?", input.Source.Items[0].ProductID).Update("list_price", 200).Error)
			case "deleted":
				require.NoError(t, db.Delete(&models.Quotation{}, input.Source.ID).Error)
			case "result":
				input.Profit = decimal.NewFromInt(99)
			case "factor":
				input.Factor = decimal.RequireFromString("1.00001")
			case "version":
				input.Source.UpdatedAt = time.Time{}
			}
			n := quoteCount(t, db)
			q, err := s.ApprovedPriceCopy(input.Source.ID, &input)
			require.True(t, errors.Is(err, ErrApprovalChanged), "%v", err)
			require.Nil(t, q)
			require.Equal(t, n, quoteCount(t, db))
		})
	}
}

func waitApprovalLock(t *testing.T, db *gorm.DB) {
	t.Helper()
	require.Eventually(t, func() bool {
		var n int64
		err := db.Raw("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'").Scan(&n).Error
		return err == nil && n > 0
	}, 5*time.Second, 10*time.Millisecond)
}

func TestApprovedPriceRechecksAfterConcurrentWriter(t *testing.T) {
	for _, field := range []string{"quotation", "product", "customer"} {
		t.Run(field, func(t *testing.T) {
			db, s, input := approvalFixture(t)
			n := quoteCount(t, db)
			tx := db.Begin()
			require.NoError(t, tx.Error)
			defer tx.Rollback()
			switch field {
			case "quotation":
				// Hold the same parent lock as the public update path. Intentionally
				// leave updated_at unchanged: item comparison must independently catch it.
				require.NoError(t, tx.Exec("SELECT id FROM quotations WHERE id=? FOR UPDATE", input.Source.ID).Error)
				require.NoError(t, tx.Model(&models.QuotationItem{}).Where("quotation_id=?", input.Source.ID).Update("quantity", 2).Error)
			case "product":
				require.NoError(t, tx.Model(&models.Product{}).Where("id=?", input.Source.Items[0].ProductID).Update("cost", 120).Error)
			case "customer":
				require.NoError(t, tx.Model(&models.Customer{}).Where("id=?", input.Source.CustomerID).Update("level", "new").Error)
			}
			done := make(chan error, 1)
			go func() { _, err := s.ApprovedPriceCopy(input.Source.ID, &input); done <- err }()
			waitApprovalLock(t, db)
			require.NoError(t, tx.Commit().Error)
			select {
			case err := <-done:
				require.ErrorIs(t, err, ErrApprovalChanged)
			case <-time.After(5 * time.Second):
				t.Fatal("copy did not finish")
			}
			require.Equal(t, n, quoteCount(t, db))
		})
	}
}

func TestApprovedPriceKeepsLocksThroughInsert(t *testing.T) {
	db, s, input := approvalFixture(t)
	entered, release := make(chan struct{}), make(chan struct{})
	require.NoError(t, db.Callback().Create().Before("gorm:create").Register("approval_test_barrier", func(tx *gorm.DB) {
		if tx.Statement.Table == "quotations" {
			close(entered)
			<-release
		}
	}))
	defer db.Callback().Create().Remove("approval_test_barrier")
	done := make(chan error, 1)
	go func() { _, err := s.ApprovedPriceCopy(input.Source.ID, &input); done <- err }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("did not reach insert")
	}
	writer := make(chan error, 1)
	go func() {
		writer <- db.Model(&models.Product{}).Where("id=?", input.Source.Items[0].ProductID).Update("cost", 120).Error
	}()
	waitApprovalLock(t, db)
	close(release)
	require.NoError(t, <-done)
	require.NoError(t, <-writer)
}
