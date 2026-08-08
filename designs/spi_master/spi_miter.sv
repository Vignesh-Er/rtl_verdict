module miter (
	input clk,
	input rst_n,
	input start,
	input [7:0] tx_data
);
	wire ref_sclk, ref_cs_n, ref_mosi, ref_busy;
	wire uut_sclk, uut_cs_n, uut_mosi, uut_busy;

	spi_master ref_i (.clk(clk), .rst_n(rst_n), .start(start), .tx_data(tx_data),
	                   .sclk(ref_sclk), .cs_n(ref_cs_n), .mosi(ref_mosi), .busy(ref_busy));
	spi_master uut_i (.clk(clk), .rst_n(rst_n), .start(start), .tx_data(tx_data),
	                   .sclk(uut_sclk), .cs_n(uut_cs_n), .mosi(uut_mosi), .busy(uut_busy));

	initial assume(!rst_n);

	always @* begin
		if (rst_n) begin
			assert (ref_sclk == uut_sclk);
			assert (ref_cs_n == uut_cs_n);
			assert (ref_mosi == uut_mosi);
			assert (ref_busy == uut_busy);
		end
	end
endmodule
