module miter (
	input clk,
	input rst_n,
	input start
);
	wire ref_busy, ref_done, uut_busy, uut_done;

	fsm ref_i (.clk(clk), .rst_n(rst_n), .start(start), .busy(ref_busy), .done(ref_done));
	fsm uut_i (.clk(clk), .rst_n(rst_n), .start(start), .busy(uut_busy), .done(uut_done));

	initial assume(!rst_n);

	always @* begin
		if (rst_n) begin
			assert (ref_busy == uut_busy);
			assert (ref_done == uut_done);
		end
	end
endmodule
